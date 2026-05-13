"""
Reachy nightly personality synthesis.

Once a day (02:30 by default, registered in main.py), this service reads:
  - the last 24 h of voice turns from ``reachy_user_memory_service``
  - the current human + relationship + persona memory blocks
  - any vault writes the agent made today (so we don't double-extract from
    research reports that already capture facts)

…and asks the configured "synthesis" LLM (kimi-heavy by default) for a
structured update:

  {
    "human_block": "<full new value>",
    "relationship_block": "<full new value>",
    "what_i_noticed": "<one paragraph>",
    "drafts_for_review": [{"category": "preference|fact", "text": "..."}]
  }

We apply the blocks atomically (with edit-history bookkeeping) and write a
dated snapshot to ``00_Meta/_agent/reachy/personality-history/YYYY-MM-DD.md``
in the Obsidian vault so the user can read, edit, or roll back what Reachy
has learned.

Drafts that need user attention raise an ``agent_alerts`` row with rule
``reachy_personality_review`` so they appear in tomorrow's morning digest.

Idempotent within a calendar day: if today's snapshot already exists, the
job exits early (lets you re-run manually without clobbering).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import structlog

from app.infrastructure.config import get_settings
from app.services.reachy_memory_blocks import (
    HUMAN_MAX_CHARS,
    RELATIONSHIP_MAX_CHARS,
    get_reachy_memory_blocks,
)
from app.services.vault_writer_service import VaultWriterService

logger = structlog.get_logger()


SNAPSHOT_SUBDIR = "00_Meta/_agent/reachy/personality-history"
TURN_LOOKBACK_HOURS = 24


@dataclass
class SynthesisResult:
    ok: bool
    snapshot_path: Optional[str] = None
    human_changed: bool = False
    relationship_changed: bool = False
    drafts: list[dict] = None
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "snapshot_path": self.snapshot_path,
            "human_changed": self.human_changed,
            "relationship_changed": self.relationship_changed,
            "drafts": self.drafts or [],
            "error": self.error,
        }


class ReachyPersonalitySynthesisService:
    _instance: Optional["ReachyPersonalitySynthesisService"] = None

    @classmethod
    def get_instance(cls) -> "ReachyPersonalitySynthesisService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def run(self, *, force: bool = False) -> SynthesisResult:
        """Synthesize today's personality update. Returns a ``SynthesisResult``.

        ``force=True`` overwrites today's snapshot if it already exists. The
        scheduler calls without force; manual re-runs (CLI / admin endpoint)
        can override.
        """
        try:
            today = date.today().isoformat()
            settings = get_settings()
            snapshot_rel = f"{SNAPSHOT_SUBDIR}/{today}.md"
            vault_writer = VaultWriterService()

            if not vault_writer.available():
                return SynthesisResult(ok=False, error="vault not available")

            # Idempotence guard
            snapshot_abs = Path(settings.vault_path) / snapshot_rel
            if snapshot_abs.exists() and not force:
                logger.info(
                    "reachy_personality_synthesis_skipped_existing",
                    path=str(snapshot_abs),
                )
                return SynthesisResult(
                    ok=True,
                    snapshot_path=str(snapshot_abs),
                    human_changed=False,
                    relationship_changed=False,
                    drafts=[],
                )

            # ---- Inputs ----
            from app.services.reachy_user_memory_service import (
                get_reachy_user_memory_service,
            )
            mem = get_reachy_user_memory_service()
            cutoff = time.time() - TURN_LOOKBACK_HOURS * 3600
            recent_turns = [t for t in mem._turns if t.ts >= cutoff]

            store = get_reachy_memory_blocks()
            human_block = store.get_block("human")
            rel_block = store.get_block("relationship")
            current_human = human_block.value if human_block else ""
            current_rel = rel_block.value if rel_block else ""

            if not recent_turns and not current_human and not current_rel:
                logger.info("reachy_personality_synthesis_nothing_to_do")
                return SynthesisResult(
                    ok=True, drafts=[], human_changed=False, relationship_changed=False
                )

            # ---- LLM call ----
            llm_payload = await self._call_llm(
                recent_turns=recent_turns,
                current_human=current_human,
                current_rel=current_rel,
            )
            if llm_payload is None:
                return SynthesisResult(ok=False, error="synthesis LLM call failed")

            new_human = (llm_payload.get("human_block") or "").strip()
            new_rel = (llm_payload.get("relationship_block") or "").strip()
            noticed = (llm_payload.get("what_i_noticed") or "").strip()
            drafts = llm_payload.get("drafts_for_review") or []
            if not isinstance(drafts, list):
                drafts = []

            # Cap to block budgets
            if len(new_human) > HUMAN_MAX_CHARS:
                new_human = new_human[:HUMAN_MAX_CHARS]
            if len(new_rel) > RELATIONSHIP_MAX_CHARS:
                new_rel = new_rel[:RELATIONSHIP_MAX_CHARS]

            human_changed = bool(new_human) and new_human != current_human
            rel_changed = bool(new_rel) and new_rel != current_rel

            if human_changed:
                await store.update_block(
                    "human",
                    new_human,
                    by="synthesis_job",
                    reason=f"nightly synthesis {today}",
                )
            if rel_changed:
                await store.update_block(
                    "relationship",
                    new_rel,
                    by="synthesis_job",
                    reason=f"nightly synthesis {today}",
                )

            # ---- Snapshot to vault ----
            body = self._render_snapshot(
                today=today,
                turns_count=len(recent_turns),
                previous_human=current_human,
                new_human=new_human,
                previous_rel=current_rel,
                new_rel=new_rel,
                noticed=noticed,
                drafts=drafts,
            )
            snap = vault_writer.write_agent_file(
                relative_path=snapshot_rel,
                content=body,
                source="reachy_personality_synthesis",
                overwrite=True,
            )

            # ---- Drafts → agent_alerts ----
            if drafts:
                try:
                    await self._raise_review_alerts(today, drafts)
                except Exception as e:  # noqa: BLE001
                    logger.debug(
                        "reachy_personality_review_alert_failed", error=str(e)
                    )

            # ---- Mirror snapshot into the Memory Tree vault ----
            # openhuman-style: every distilled snapshot also lands as a
            # browsable .md file under ``sources/personality/L0/`` so the
            # user can read what Zero learned today in the MemoryVault UI.
            try:
                from app.services.memory_tree import get_memory_tree
                tree = get_memory_tree()
                body_parts: list[str] = [
                    f"# Personality synthesis — {today}",
                    "",
                    f"## What I noticed\n{noticed or '_(nothing noted)_'}",
                ]
                if new_human and new_human != current_human:
                    body_parts.append("\n## Updated human block\n" + new_human)
                if new_rel and new_rel != current_rel:
                    body_parts.append("\n## Updated relationship block\n" + new_rel)
                if drafts:
                    bullets = "\n".join(
                        f"- ({d.get('category', '?')}) {d.get('text', '')}" for d in drafts
                    )
                    body_parts.append(f"\n## Drafts for review\n{bullets}")
                await tree.write_chunk(
                    "personality",
                    "\n".join(body_parts),
                    level=0,
                    title=f"Synthesis {today}",
                    tags=["personality", "synthesis"],
                )
            except Exception as e:  # noqa: BLE001
                logger.debug(
                    "reachy_personality_vault_write_failed", error=str(e)
                )

            logger.info(
                "reachy_personality_synthesis_done",
                snapshot=snap.get("relative"),
                turns=len(recent_turns),
                human_changed=human_changed,
                rel_changed=rel_changed,
                drafts=len(drafts),
            )
            return SynthesisResult(
                ok=True,
                snapshot_path=snap.get("path"),
                human_changed=human_changed,
                relationship_changed=rel_changed,
                drafts=drafts,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("reachy_personality_synthesis_error", error=str(e))
            return SynthesisResult(ok=False, error=str(e))

    # --------------------------------------------------------------- helpers

    async def _call_llm(
        self,
        *,
        recent_turns: list,
        current_human: str,
        current_rel: str,
    ) -> Optional[dict]:
        """Call the unified LLM client with a strict-JSON synthesis prompt.

        Pins the model to ``kimi/kimi-k2.6`` (fast cloud, already used by
        ``research`` and ``planning`` task types in the router) instead of
        falling through to the default ``vllm/qwen3-chat`` — local vLLM is
        too slow for a 2200-token synthesis call (would exceed the 90s
        timeout). Moonshot's hosted Kimi serves the same prompt in 2-5s.
        """
        transcript_parts: list[str] = []
        for t in recent_turns[-200:]:
            user_text = (t.user_text or "").strip()
            reachy_text = (t.reachy_text or "").strip()
            if not user_text and not reachy_text:
                continue
            ts_str = datetime.fromtimestamp(t.ts, tz=timezone.utc).strftime("%H:%M")
            transcript_parts.append(
                f"[{ts_str}] ({t.persona_id})\n  USER: {user_text}\n  REACHY: {reachy_text}"
            )
        transcript = "\n\n".join(transcript_parts) or "(no turns in the last 24 hours)"

        system = (
            "You are Reachy's overnight memory consolidator. You read the past "
            "day of voice turns plus the current memory blocks, and produce an "
            "updated memory state.\n\n"
            "Return ONE JSON object — no prose, no code fences. Schema:\n"
            "{\n"
            '  "human_block": "<full replacement text — durable facts about '
            'the user written as a profile, headings allowed>",\n'
            '  "relationship_block": "<full replacement text — recurring '
            'topics, shared shorthand, threads, written tersely>",\n'
            '  "what_i_noticed": "<one paragraph in first person about '
            'something interesting from today, plain prose>",\n'
            '  "drafts_for_review": [{"category": "preference|fact|topic", '
            '"text": "<one short line>"}]\n'
            "}\n\n"
            "Rules:\n"
            "- Preserve durable facts from the previous human_block. Only "
            "remove a fact if the past day clearly contradicts it.\n"
            "- Add only what's clearly true from the transcript. Be "
            "conservative.\n"
            "- relationship_block tracks recurring topics, the user's "
            "ongoing projects, inside shorthand — not point-in-time facts.\n"
            "- drafts_for_review is for low-confidence guesses you want the "
            "user to confirm before they become durable. Keep this list "
            "short (0-3 items).\n"
            "- Never invent facts. Reachy must remain trustworthy.\n"
            "- Hard caps: human_block ≤ 3000 chars, relationship_block ≤ "
            "2000 chars, what_i_noticed ≤ 500 chars."
        )

        user_payload = (
            f"## CURRENT human_block ({len(current_human)} chars)\n"
            f"{current_human or '(empty)'}\n\n"
            f"## CURRENT relationship_block ({len(current_rel)} chars)\n"
            f"{current_rel or '(empty)'}\n\n"
            f"## TRANSCRIPT — last {TURN_LOOKBACK_HOURS}h ({len(recent_turns)} turns)\n"
            f"{transcript}\n"
        )

        try:
            from app.infrastructure.unified_llm_client import get_unified_llm_client
            client = get_unified_llm_client()
            response = await asyncio.wait_for(
                client.chat(
                    prompt=user_payload,
                    system=system,
                    model="kimi/kimi-k2.6",
                    task_type="synthesis",
                    temperature=0.4,
                    max_tokens=2200,
                ),
                timeout=90.0,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("synthesis_llm_call_failed", error=str(e))
            return None

        text = response if isinstance(response, str) else (
            response.get("content") or response.get("response") or ""
        )
        return _parse_strict_json(text)

    def _render_snapshot(
        self,
        *,
        today: str,
        turns_count: int,
        previous_human: str,
        new_human: str,
        previous_rel: str,
        new_rel: str,
        noticed: str,
        drafts: list,
    ) -> str:
        prev_human_hash = hashlib.sha256(previous_human.encode("utf-8")).hexdigest()[:12]
        new_human_hash = hashlib.sha256(new_human.encode("utf-8")).hexdigest()[:12]
        prev_rel_hash = hashlib.sha256(previous_rel.encode("utf-8")).hexdigest()[:12]
        new_rel_hash = hashlib.sha256(new_rel.encode("utf-8")).hexdigest()[:12]

        lines: list[str] = [
            "---",
            f"id: reachy-personality-{today}",
            "type: personality-snapshot",
            "partition: inbox",
            f"date: {today}",
            f"turns_synthesized: {turns_count}",
            f"human_block_before_hash: {prev_human_hash}",
            f"human_block_after_hash: {new_human_hash}",
            f"relationship_block_before_hash: {prev_rel_hash}",
            f"relationship_block_after_hash: {new_rel_hash}",
            "agent_writable: []",
            "tags: [reachy, personality, agent]",
            "---",
            "",
            f"# Reachy personality — {today}",
            "",
            f"Synthesized from {turns_count} voice turns in the last "
            f"{TURN_LOOKBACK_HOURS} hours.",
            "",
        ]

        if noticed:
            lines += ["## What I noticed", "", noticed.strip(), ""]

        lines += ["## human_block (after)", ""]
        lines.append(new_human.strip() or "_(empty)_")
        lines.append("")

        if previous_human and previous_human != new_human:
            lines += ["<details><summary>Previous human_block</summary>", "", previous_human.strip(), "", "</details>", ""]

        lines += ["## relationship_block (after)", ""]
        lines.append(new_rel.strip() or "_(empty)_")
        lines.append("")

        if previous_rel and previous_rel != new_rel:
            lines += ["<details><summary>Previous relationship_block</summary>", "", previous_rel.strip(), "", "</details>", ""]

        if drafts:
            lines += ["## Drafts for review", ""]
            for d in drafts:
                cat = (d.get("category") or "topic")[:20]
                txt = (d.get("text") or "").strip()[:200]
                if txt:
                    lines.append(f"- **{cat}**: {txt}")
            lines.append("")
            lines += [
                "_These are low-confidence guesses I want you to confirm "
                "before they become durable. Edit the human_block above to "
                "approve or remove them._",
                "",
            ]

        return "\n".join(lines)

    async def _raise_review_alerts(self, today: str, drafts: list) -> None:
        """Insert one ``agent_alerts`` row when drafts exist so the morning
        digest surfaces them. Best-effort — failure here doesn't fail the
        synthesis. Mirrors the ``drift_scanner_service._upsert_alert`` pattern
        (SELECT-then-INSERT) since ``agent_alerts`` has no unique index that
        ON CONFLICT could target.
        """
        if not drafts:
            return
        try:
            import uuid
            from app.db.models import AgentAlertModel
            from app.infrastructure.database import get_session
            from sqlalchemy import select
        except Exception:
            return

        summary = (
            f"Reachy has {len(drafts)} low-confidence memory drafts from "
            f"{today} that need your review."
        )
        details = {"drafts": drafts, "snapshot_date": today}
        async with get_session() as session:
            existing = await session.execute(
                select(AgentAlertModel.id).where(
                    AgentAlertModel.rule == "reachy_personality_review",
                    AgentAlertModel.entity_id == today,
                    AgentAlertModel.status == "open",
                )
            )
            if existing.scalar_one_or_none():
                # Already raised for today's snapshot.
                return
            session.add(
                AgentAlertModel(
                    id=f"alrt-{uuid.uuid4().hex[:12]}",
                    rule="reachy_personality_review",
                    severity="info",
                    salience=0.6,
                    entity_type="reachy_personality_snapshot",
                    entity_id=today,
                    summary=summary,
                    details=details,
                    status="open",
                )
            )
            await session.commit()


def get_reachy_personality_synthesis_service() -> ReachyPersonalitySynthesisService:
    return ReachyPersonalitySynthesisService.get_instance()


# ---------------------------------------------------------------- helpers


def _parse_strict_json(text: str) -> Optional[dict]:
    """Tolerant JSON-object extractor: strips fences, locates first {…}."""
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```\s*$", "", s)
    match = re.search(r"\{.*\}", s, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


# ---------------------------------------------------------------- CLI


async def _amain(force: bool) -> int:
    svc = get_reachy_personality_synthesis_service()
    result = await svc.run(force=force)
    print(json.dumps(result.to_dict(), indent=2, default=str))
    return 0 if result.ok else 1


if __name__ == "__main__":
    import sys
    forced = "--run-now" in sys.argv or "--force" in sys.argv
    raise SystemExit(asyncio.run(_amain(forced)))
