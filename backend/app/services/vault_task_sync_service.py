"""Vault Task Sync — bidirectional bridge between daily-note checkboxes and TaskModel.

Phase 3 of the SecondBrain plan. Scans `20_Calendar/Daily/*.md` (and any other
whitelisted note) for `- [ ] …` and `- [x] …` items under `## Inbox`, `## Today`,
or `## Tasks` headings. Each line becomes or updates a TaskModel row:

  - [ ] <text>  <!-- zero-task: task_id -->

The trailing HTML comment is the persistence seam — after first sync we annotate
the vault line with the task_id so the next scan knows this line already maps
to a Zero task. That lets the scanner be idempotent + source-of-truth is the
vault (not the DB).

Status mapping: unchecked -> todo, checked -> done. Going from done -> todo in
the vault reopens the task. Editing the text in the vault updates TaskModel.title.

This runs via the vault indexer's same tick (every 2 min) — cheap because only
daily notes get scanned.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import structlog
from sqlalchemy import select, update

from app.db.models import TaskModel
from app.infrastructure.config import get_settings
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)


_CHECKBOX_RE = re.compile(
    r"^(?P<indent>\s*)-\s\[(?P<state>[ xX])\]\s+(?P<text>.*?)(?:\s*<!--\s*zero-task:\s*(?P<task_id>[a-zA-Z0-9_-]+)\s*-->)?\s*$"
)
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$")
_ACTIVE_SECTIONS = {"inbox", "today", "tasks"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class VaultTaskSyncService:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._vault = Path(self._settings.vault_path)

    def available(self) -> bool:
        return self._vault.is_dir()

    async def sync_all(self, max_notes: int = 14) -> dict[str, Any]:
        """Scan daily notes (most recent first) for checkbox tasks."""
        if not self.available():
            return {"status": "skipped", "reason": "vault_unavailable"}

        daily_dir = self._vault / self._settings.vault_daily_subdir
        if not daily_dir.is_dir():
            return {"status": "skipped", "reason": "no_daily_dir", "path": str(daily_dir)}

        notes = sorted(daily_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:max_notes]
        created = 0
        updated = 0
        closed = 0
        reopened = 0
        annotated = 0

        for note in notes:
            stats = await self._sync_note(note)
            created += stats["created"]
            updated += stats["updated"]
            closed += stats["closed"]
            reopened += stats["reopened"]
            annotated += stats["annotated"]

        logger.info(
            "vault_task_sync",
            notes_scanned=len(notes),
            created=created,
            updated=updated,
            closed=closed,
            reopened=reopened,
            annotated=annotated,
        )
        return {
            "status": "ok",
            "notes_scanned": len(notes),
            "created": created,
            "updated": updated,
            "closed": closed,
            "reopened": reopened,
            "annotated": annotated,
        }

    async def _sync_note(self, note: Path) -> dict[str, int]:
        stats = {"created": 0, "updated": 0, "closed": 0, "reopened": 0, "annotated": 0}
        try:
            lines = note.read_text(encoding="utf-8").splitlines()
        except Exception:  # noqa: BLE001
            return stats

        in_active_section = False
        changed = False

        for i, line in enumerate(lines):
            h = _HEADING_RE.match(line)
            if h:
                heading = h.group(1).strip().lower().lstrip("#").strip()
                in_active_section = any(heading == s or heading.startswith(s + " ") for s in _ACTIVE_SECTIONS)
                continue

            if not in_active_section:
                continue

            m = _CHECKBOX_RE.match(line)
            if not m:
                continue

            indent = m.group("indent") or ""
            state = m.group("state").lower()
            text = (m.group("text") or "").strip()
            task_id = m.group("task_id")
            target_status = "done" if state == "x" else "todo"

            if not text:
                continue

            if task_id:
                # Existing task — check if status changed.
                task = await self._get_task(task_id)
                if task is None:
                    continue
                if task.title != text:
                    await self._update_task(task_id, title=text)
                    stats["updated"] += 1
                if task.status != target_status:
                    now = _now()
                    kwargs: dict[str, Any] = {"status": target_status}
                    if target_status == "done" and task.status != "done":
                        kwargs["completed_at"] = now
                        stats["closed"] += 1
                    elif target_status == "todo" and task.status == "done":
                        kwargs["completed_at"] = None
                        stats["reopened"] += 1
                    await self._update_task(task_id, **kwargs)
            else:
                # New task — create + annotate vault line with task_id.
                new_id = await self._create_task(title=text, status=target_status, vault_path=note.name)
                stats["created"] += 1
                lines[i] = f"{indent}- [{m.group('state')}] {text}  <!-- zero-task: {new_id} -->"
                changed = True
                stats["annotated"] += 1

        if changed:
            try:
                note.write_text("\n".join(lines) + "\n", encoding="utf-8")
            except Exception as e:  # noqa: BLE001
                logger.warning("vault_task_sync_annotate_failed", path=str(note), error=str(e))

        return stats

    async def _get_task(self, task_id: str) -> Optional[TaskModel]:
        async with get_session() as session:
            return await session.get(TaskModel, task_id)

    async def _update_task(self, task_id: str, **kwargs: Any) -> None:
        async with get_session() as session:
            await session.execute(update(TaskModel).where(TaskModel.id == task_id).values(**kwargs))
            await session.commit()

    async def _create_task(self, *, title: str, status: str, vault_path: str) -> str:
        task_id = f"vt-{uuid.uuid4().hex[:12]}"
        async with get_session() as session:
            session.add(
                TaskModel(
                    id=task_id,
                    title=title,
                    status=status,
                    category="chore",
                    priority="medium",
                    points=1,
                    source="VAULT_CHECKBOX",
                    description=f"Imported from vault: {vault_path}",
                )
            )
            await session.commit()
        return task_id


_singleton: Optional[VaultTaskSyncService] = None


def get_vault_task_sync() -> VaultTaskSyncService:
    global _singleton
    if _singleton is None:
        _singleton = VaultTaskSyncService()
    return _singleton
