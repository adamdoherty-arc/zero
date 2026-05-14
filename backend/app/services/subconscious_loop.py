"""
Subconscious loop â€” background self-reflection while the user is away.

openhuman calls this the "subconscious"; Zero's equivalent: an idle-aware
``asyncio`` task that wakes every ``interval_minutes``, looks at recent
vault writes + active integrations, asks the local LLM (via ``hint:reflection``)
to produce a small "insight" object, and stores it in the Memory Vault global
digest folder.

Insights are also appended to an in-memory rolling buffer (last 50) so the
UI can show "what Zero has been thinking about" without a DB read.

Cheap by default: uses the local provider unless the active hint preset
overrides. Skips a tick if there's been no fresh vault activity in the
window â€” no point reflecting on nothing.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections import deque
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_utc().isoformat(timespec="seconds").replace("+00:00", "Z")


DEFAULT_INTERVAL_MIN = int(os.getenv("ZERO_SUBCONSCIOUS_INTERVAL_MIN", "15"))
_MAX_INSIGHTS_BUFFER = 50


class SubconsciousLoop:
    def __init__(self, interval_minutes: int = DEFAULT_INTERVAL_MIN) -> None:
        self._interval = max(1, interval_minutes)
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_ran_at: Optional[str] = None
        self._insights: deque[dict] = deque(maxlen=_MAX_INSIGHTS_BUFFER)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._run())
        logger.info("subconscious_started", interval_min=self._interval)

    async def stop(self) -> None:
        self._running = False
        task = self._task
        self._task = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        logger.info("subconscious_stopped")

    def set_interval(self, minutes: int) -> None:
        self._interval = max(1, minutes)

    def status(self) -> dict:
        return {
            "running": self._running,
            "interval_minutes": self._interval,
            "last_ran_at": self._last_ran_at,
            "insights_buffered": len(self._insights),
        }

    def recent_insights(self, limit: int = 20) -> list[dict]:
        return list(self._insights)[:limit]

    # ------------------------------------------------------------------
    # Loop
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        while self._running:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                logger.warning("subconscious_tick_failed", error=str(e))
            try:
                await asyncio.sleep(self._interval * 60)
            except asyncio.CancelledError:
                break

    async def run_once(self) -> dict:
        """Single reflection pass. Returns the produced insight dict."""
        signals = await self._gather_signals()
        if not signals.get("has_activity"):
            self._last_ran_at = _now_iso()
            return {"status": "skipped", "reason": "no_recent_activity"}

        prompt = self._build_prompt(signals)
        insight = await self._ask_local_llm(prompt)
        if not insight:
            self._last_ran_at = _now_iso()
            return {"status": "llm_unavailable"}

        # Persist + buffer.
        await self._persist_insight(insight, signals)
        record = {
            "ts": _now_iso(),
            "insight": insight,
            "signal_count": signals.get("count", 0),
        }
        self._insights.appendleft(record)
        self._last_ran_at = record["ts"]
        return {"status": "ok", **record}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _gather_signals(self) -> dict:
        """Inspect vault + integration sync state for recent activity."""
        from app.services.memory_tree import get_memory_tree
        from app.services.integrations.composio_provider import get_composio_provider

        tree = get_memory_tree()
        stats = tree.stats()

        # Look at the 30 most recent vault entries across all scopes.
        from app.services.memory_tree.vault import list_entries
        entries = list_entries(tree.root)
        entries.sort(key=lambda e: str(e.path), reverse=True)
        recent = entries[:30]

        cutoff = _now_utc() - timedelta(hours=24)
        cutoff_str = cutoff.isoformat(timespec="seconds").replace("+00:00", "")
        has_activity = False
        for e in recent:
            created = e.frontmatter.get("created", "")
            created_str = str(created).replace("Z", "").replace("+00:00", "")
            if created_str and created_str >= cutoff_str:
                has_activity = True
                break

        return {
            "has_activity": has_activity,
            "count": len(recent),
            "recent_titles": [e.frontmatter.get("title", e.path.stem) for e in recent[:10]],
            "sources": list(stats.get("sources", {}).keys()),
            "connected_integrations": get_composio_provider().list_connected(),
        }

    def _build_prompt(self, signals: dict) -> str:
        bullets = "\n".join(f"- {t}" for t in signals.get("recent_titles", []))
        return (
            "You are Zero's subconscious â€” a quiet, reflective layer that "
            "operates while the user is away. Look at the recent activity "
            "below and produce ONE small insight that might be useful to "
            "surface later. Be specific, brief, and only output JSON.\n\n"
            f"Connected integrations: {', '.join(signals.get('connected_integrations', [])) or 'none'}\n"
            f"Recent vault entries:\n{bullets}\n\n"
            'Output JSON: {"theme": "...", "observation": "one sentence", '
            '"suggested_action": "one sentence or null"}'
        )

    async def _ask_local_llm(self, prompt: str) -> Optional[dict]:
        try:
            from app.infrastructure.llm_router import get_llm_router
            from app.infrastructure.bifrost_client import get_bifrost_client

            router = get_llm_router()
            spec = router.resolve("hint:reflection")
            provider, _, model = spec.partition("/")
            logger.info("subconscious_llm", provider=provider, model=model)

            bifrost = get_bifrost_client()
            if not bifrost.is_available():
                return None
            raw = await bifrost.complete(
                model="hint:reflection",
                messages=[
                    {
                        "role": "system",
                        "content": "Return only a compact JSON object.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=400,
            )
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                start = raw.find("{")
                end = raw.rfind("}")
                if start < 0 or end <= start:
                    return None
                parsed = json.loads(raw[start : end + 1])
            if not isinstance(parsed, dict) or not parsed.get("observation"):
                return None
            parsed["_model"] = spec
            return parsed
        except Exception as e:  # noqa: BLE001
            logger.debug("subconscious_llm_failed", error=str(e))
            return None

    async def _persist_insight(self, insight: dict, signals: dict) -> None:
        from app.services.memory_tree import get_memory_tree
        tree = get_memory_tree()
        body = (
            f"## Theme\n{insight.get('theme', '')}\n\n"
            f"## Observation\n{insight.get('observation', '')}\n\n"
            f"## Suggested action\n{insight.get('suggested_action') or '_(none)_'}\n\n"
            f"## Signals\n```json\n{json.dumps(signals, indent=2)}\n```"
        )
        await tree.write_chunk(
            "subconscious",
            body,
            level=0,
            title=insight.get("theme") or "Subconscious insight",
            tags=["subconscious", "reflection"],
        )

        # Surface to the user only when the insight proposes an action.
        # Observation-only ticks are vault-only â€” we don't want to spam
        # agent_alerts with every idle reflection.
        if not insight.get("suggested_action"):
            return

        # Respect the companion service's proactive-nudge policy. When the
        # user is in "off" mode (or has disabled proactive nudges in any
        # mode), the subconscious silently writes to the vault but does
        # NOT pop an agent_alert. When in "focus" the cap is tighter than
        # "ambient" â€” we enforce both here so the subconscious can't out-talk
        # the companion's existing nudge budget.
        try:
            from app.services.reachy_companion_service import (
                get_reachy_companion_service,
            )
            companion = get_reachy_companion_service()
            verdict = companion.action_allowed("proactive_nudge")
            if not verdict.get("allowed"):
                logger.info(
                    "subconscious_alert_silenced",
                    reason=verdict.get("reason"),
                )
                return
            if not self._under_nudge_budget(companion):
                logger.info("subconscious_alert_silenced", reason="nudge_budget_full")
                return
            from app.models.reachy_companion import CompanionEventCreate
            companion.record_event(
                CompanionEventCreate(
                    type="proactive_nudge",
                    summary=insight.get("observation") or "Subconscious insight",
                    detail=insight.get("suggested_action"),
                    source="subconscious_loop",
                )
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("subconscious_companion_gate_failed", error=str(e))
            # Fall through to the agent_alert insert â€” the gate is advisory,
            # not a hard requirement. Vault write already happened above.

        try:
            import uuid as _uuid
            from app.db.models import AgentAlertModel
            from app.infrastructure.database import get_session
            from datetime import datetime as _dt

            async with get_session() as session:
                session.add(
                    AgentAlertModel(
                        id=f"sub-{_uuid.uuid4().hex[:12]}",
                        rule="subconscious_insight",
                        severity="info",
                        salience=0.4,
                        entity_type="subconscious",
                        entity_id=_dt.utcnow().strftime("%Y%m%d-%H%M%S"),
                        summary=insight.get("observation") or "Subconscious insight",
                        details={
                            "theme": insight.get("theme"),
                            "observation": insight.get("observation"),
                            "suggested_action": insight.get("suggested_action"),
                            "signals": signals,
                        },
                    )
                )
                await session.commit()
        except Exception as e:  # noqa: BLE001
            logger.debug("subconscious_alert_skipped", error=str(e))

    def _under_nudge_budget(self, companion) -> bool:
        """Check the per-mode max_proactive_events_per_hour cap.

        Walks the companion service's recent event log and counts
        ``proactive_nudge`` rows in the last hour. Returns True iff we're
        below the cap on the current mode.
        """
        try:
            policy = companion.get_policy()
            cap = int(policy.max_proactive_events_per_hour or 0)
        except Exception:
            cap = 0
        if cap <= 0:
            # Either off mode or unconfigured â€” silent by design.
            return False
        try:
            from datetime import datetime, timedelta, timezone
            cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
            recent = companion.list_events(limit=200)
            count = 0
            for ev in recent:
                ts = getattr(ev, "created_at", None) or getattr(ev, "ts", None)
                if ts is None:
                    continue
                if isinstance(ts, str):
                    try:
                        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                if ts >= cutoff and getattr(ev, "type", "") == "proactive_nudge":
                    count += 1
            return count < cap
        except Exception as e:  # noqa: BLE001
            logger.debug("subconscious_budget_check_failed", error=str(e))
            return True


@lru_cache(maxsize=1)
def get_subconscious_loop() -> SubconsciousLoop:
    return SubconsciousLoop()
