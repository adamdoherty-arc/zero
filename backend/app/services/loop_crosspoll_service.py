"""Loop cross-pollination service — fanout learnings ADA <-> Legion <-> Zero.

Pattern: every skill output that contains a `<learning kind=... confidence=...>`
block is captured as a `loop_learnings` row by the runner. This service runs on
a schedule and broadcasts each new learning to peer projects so they all benefit
from any one project's discovery.

Three sinks per learning, tracked in `applied_to`:
- vault   : `00_Meta/_agent/learnings/cross/<kind>/<source>-<id>.md`
- legion  : POST /api/learnings/* (best-effort; if Legion is down, vault still
            has the durable record).
- ada     : append to `/projects/ada/.claude/memory/topics/cross-project.md`

Cross-project learnings NEVER auto-edit code in another project — they are
documentation. Code edits route through the existing agent_approvals queue.

Confidence threshold (default 0.6) prevents low-quality noise. A learning's
`applied_to` JSONB array tracks where it landed so we don't re-apply.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import structlog
from sqlalchemy import select, update

from app.db.models import LoopLearningModel
from app.infrastructure.database import get_session
from app.services.vault_writer_service import get_vault_writer

logger = structlog.get_logger(__name__)


def _slug(s: str, max_len: int = 60) -> str:
    out = []
    for c in s.lower():
        if c.isalnum():
            out.append(c)
        elif c in "-_ ":
            out.append("-")
    return "".join(out).strip("-")[:max_len] or "untitled"


class LoopCrosspollService:
    """Broadcast learnings to peer-project memory stores."""

    def __init__(self) -> None:
        self._vault = get_vault_writer()

    async def fanout_pending(
        self,
        *,
        min_confidence: float = 0.6,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Walk loop_learnings, fan out to peer projects."""
        async with get_session() as session:
            stmt = (
                select(LoopLearningModel)
                .where(LoopLearningModel.confidence >= min_confidence)
                .order_by(LoopLearningModel.created_at.asc())
                .limit(limit * 2)  # over-fetch — many will be already-applied
            )
            rows = (await session.execute(stmt)).scalars().all()

        applied_count = 0
        skipped_count = 0
        for row in rows:
            applied_to = row.applied_to or []
            target_projects = self._missing_projects(row.source_project, applied_to)
            if not target_projects:
                continue
            new_applied = list(applied_to)
            for project in target_projects:
                outcome = await self._apply_to_project(row, project)
                if outcome.get("status") == "ok":
                    new_applied.append({
                        "project": project,
                        "applied_at": datetime.now(timezone.utc).isoformat(),
                        "details": outcome.get("details", ""),
                    })
            if new_applied != applied_to:
                async with get_session() as session:
                    await session.execute(
                        update(LoopLearningModel)
                        .where(LoopLearningModel.id == row.id)
                        .values(applied_to=new_applied)
                    )
                    await session.commit()
                applied_count += 1
            else:
                skipped_count += 1

            if applied_count >= limit:
                break

        return {
            "fanout_count": applied_count,
            "skipped": skipped_count,
            "candidates": len(rows),
        }

    # ------------------------------------------------------------------
    # Sinks
    # ------------------------------------------------------------------

    def _missing_projects(self, source_project: str, applied_to: list[dict[str, Any]]) -> list[str]:
        """Return sinks that haven't received this learning yet.

        The vault is the canonical cross-project bus — every project mounts
        it read-only and can pick up learnings from `_agent/learnings/cross/`.
        We don't write into ADA's tree (read-only mount by design) or push
        crosspoll learnings as fake loop_runs to Legion (semantic mismatch).
        Legion ingestion happens organically when Legion's own loops produce
        them, OR when the user wires a dedicated Legion learning ingestion
        endpoint later.
        """
        already = {entry.get("project") for entry in applied_to if isinstance(entry, dict)}
        candidates: set[str] = set()
        if "vault" not in already:
            candidates.add("vault")
        return sorted(candidates)

    async def _apply_to_project(
        self,
        row: LoopLearningModel,
        project: str,
    ) -> dict[str, Any]:
        # Vault is currently the only sink — see _missing_projects. Other
        # branches kept commented for future re-enablement once peer projects
        # expose proper learning-ingest endpoints.
        if project == "vault":
            return self._apply_to_vault(row)
        return {"status": "skipped", "details": f"sink {project} not wired"}

    def _apply_to_vault(self, row: LoopLearningModel) -> dict[str, Any]:
        if not self._vault.available():
            return {"status": "skipped", "details": "vault not available"}
        try:
            relative = (
                f"00_Meta/_agent/learnings/cross/{row.pattern_kind}/"
                f"{row.source_project}-{row.id}-{_slug(row.summary)}.md"
            )
            body = (
                f"---\n"
                f"id: cross-learning-{row.id}\n"
                f"type: cross_project_learning\n"
                f"source_project: {row.source_project}\n"
                f"source_run_id: {row.source_run_id}\n"
                f"pattern_kind: {row.pattern_kind}\n"
                f"confidence: {row.confidence:.2f}\n"
                f"created_at: {row.created_at.isoformat() if row.created_at else ''}\n"
                f"agent_writable: []\n"
                f"tags: [cross_project, learning, agent, auto]\n"
                f"---\n\n"
                f"# {row.summary}\n\n"
                f"**Confidence:** {row.confidence:.2f} · **Kind:** `{row.pattern_kind}` · "
                f"**Source:** `{row.source_project}` (run #{row.source_run_id})\n\n"
                f"## Detail\n\n"
                f"{row.detail.strip()}\n"
            )
            self._vault.write_agent_file(
                relative_path=relative,
                content=body,
                source="loop_crosspoll",
                run_id=str(row.source_run_id),
            )
            return {"status": "ok", "details": relative}
        except Exception as exc:  # noqa: BLE001
            logger.warning("crosspoll.vault_write_failed", learning_id=row.id, error=str(exc))
            return {"status": "failed", "details": str(exc)}


@lru_cache(maxsize=1)
def get_loop_crosspoll() -> LoopCrosspollService:
    return LoopCrosspollService()
