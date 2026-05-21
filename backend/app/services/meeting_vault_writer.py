"""F-44 — write each completed meeting to a per-meeting markdown file in
the Obsidian vault.

Path: ``/vault/Meetings/<YYYY>/<MM>/<id>-<slug>.md``

Frontmatter mirrors MeetingSummaryModel:

    ---
    title: ...
    when: 2026-05-21T14:00:00+00:00
    meeting_id: ...
    attendees: [a@x.com, b@x.com]
    duration_minutes: 32
    has_recording: true
    has_transcript_segments: 142
    key_topics: [...]
    action_items_count: 5
    decisions_count: 2
    private: false
    ---

Body lists action items + decisions + a transcript-preview block linking
to the full search route. Idempotent — calling write() twice with the
same meeting_id overwrites the file. Also maintains a per-month index
file (``/vault/Meetings/<YYYY>/<MM>/_index.md``).
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import structlog

logger = structlog.get_logger(__name__)


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str, max_len: int = 60) -> str:
    cleaned = _SLUG_RE.sub("-", (text or "").strip().lower()).strip("-")
    return (cleaned or "meeting")[:max_len]


def _fm_dump(d: dict[str, Any]) -> str:
    """Tiny YAML-ish frontmatter writer. Lists rendered inline."""
    lines = ["---"]
    for k, v in d.items():
        if v is None:
            continue
        if isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        elif isinstance(v, (int, float)):
            lines.append(f"{k}: {v}")
        elif isinstance(v, list):
            safe = [str(x).replace('"', "'") for x in v]
            lines.append(f"{k}: [" + ", ".join(f'"{s}"' if any(c in s for c in ", :#[]") else s for s in safe) + "]")
        else:
            s = str(v).replace('"', "'")
            if any(c in s for c in [":", "#", "[", "]"]):
                lines.append(f'{k}: "{s}"')
            else:
                lines.append(f"{k}: {s}")
    lines.append("---")
    return "\n".join(lines)


class MeetingVaultWriter:
    def __init__(self, root: Path | None = None) -> None:
        # /vault is the in-container mount of C:\code\vault\ObsidianZero.
        default = Path(os.getenv("ZERO_VAULT_ROOT", "/vault"))
        self._root = (root or default).resolve()
        self._meetings_root = self._root / "Meetings"
        # Don't auto-mkdir if /vault isn't mounted — the caller will
        # log+continue. Avoids polluting random container filesystems.

    def vault_available(self) -> bool:
        try:
            return self._root.exists() and self._root.is_dir()
        except Exception:
            return False

    def write(
        self,
        *,
        meeting_id: str,
        title: str,
        start_time: datetime | None,
        end_time: datetime | None,
        attendees: Iterable[str] | None,
        summary_text: str,
        key_topics: Iterable[str] | None,
        action_items: list[dict[str, Any]] | None,
        decisions: list[dict[str, Any]] | None,
        transcript_segment_count: int,
        recording_path: str | None,
        speakers: Iterable[str] | None,
        private: bool = False,
    ) -> dict[str, Any]:
        if not self.vault_available():
            return {"ok": False, "reason": "vault_not_mounted", "vault_root": str(self._root)}

        when_dt = start_time or datetime.now(timezone.utc)
        if when_dt.tzinfo is None:
            when_dt = when_dt.replace(tzinfo=timezone.utc)
        year_dir = self._meetings_root / f"{when_dt.year:04d}"
        month_dir = year_dir / f"{when_dt.month:02d}"
        month_dir.mkdir(parents=True, exist_ok=True)

        duration_min: int | None = None
        if start_time and end_time:
            try:
                duration_min = max(0, int((end_time - start_time).total_seconds() / 60))
            except Exception:
                duration_min = None

        attendees_list = [str(a) for a in (attendees or []) if a]
        action_items = list(action_items or [])
        decisions = list(decisions or [])
        key_topics_list = [str(k) for k in (key_topics or []) if k]
        speakers_list = sorted({str(s) for s in (speakers or []) if s})

        slug = _slug(title)
        filename = f"{meeting_id[:12]}-{slug}.md"
        path = month_dir / filename

        # Skip the body+write when this is a private meeting — only write
        # a minimal stub so the user can still tell it happened (calendar
        # consistency) but the transcript content stays out of the vault.
        if private:
            body = (
                f"# {title}\n\n"
                f"_(Private meeting. Transcript and action items intentionally not written to vault.)_\n"
            )
            fm = _fm_dump({
                "title": title,
                "when": when_dt.isoformat(),
                "meeting_id": meeting_id,
                "duration_minutes": duration_min,
                "private": True,
            })
            content = f"{fm}\n\n{body}"
            path.write_text(content, encoding="utf-8")
            self._rewrite_index(month_dir, when_dt)
            return {"ok": True, "path": str(path), "private": True}

        fm = _fm_dump({
            "title": title,
            "when": when_dt.isoformat(),
            "meeting_id": meeting_id,
            "attendees": attendees_list,
            "duration_minutes": duration_min,
            "has_recording": bool(recording_path),
            "transcript_segments": transcript_segment_count,
            "key_topics": key_topics_list,
            "action_items_count": len(action_items),
            "decisions_count": len(decisions),
            "speakers": speakers_list,
            "private": False,
        })
        body_lines = [f"# {title}", ""]
        if summary_text.strip():
            body_lines += ["## Summary", "", summary_text.strip(), ""]
        if action_items:
            body_lines += ["## Action items", ""]
            for ai in action_items:
                desc = str(ai.get("description") or "").strip()
                owner = str(ai.get("owner") or "").strip()
                due = str(ai.get("due") or "").strip()
                if not desc:
                    continue
                extras = []
                if owner:
                    extras.append(f"owner: {owner}")
                if due:
                    extras.append(f"due: {due}")
                body_lines.append(
                    f"- [ ] {desc}" + (f" ({', '.join(extras)})" if extras else "")
                )
            body_lines.append("")
        if decisions:
            body_lines += ["## Decisions", ""]
            for d in decisions:
                if isinstance(d, dict):
                    txt = str(d.get("description") or d.get("text") or "").strip()
                else:
                    txt = str(d).strip()
                if txt:
                    body_lines.append(f"- {txt}")
            body_lines.append("")
        body_lines += [
            "## Sources",
            "",
            f"- transcript: /api/meeting-transcriptions/{meeting_id}",
            f"- search: /api/meeting-search/?meeting_id={meeting_id}",
        ]
        if recording_path:
            body_lines.append(f"- recording: `{recording_path}`")

        content = f"{fm}\n\n" + "\n".join(body_lines).rstrip() + "\n"
        path.write_text(content, encoding="utf-8")
        self._rewrite_index(month_dir, when_dt)
        return {"ok": True, "path": str(path), "private": False}

    def _rewrite_index(self, month_dir: Path, anchor_dt: datetime) -> None:
        """Per-month index file listing every meeting in the month."""
        try:
            md_files = sorted(
                [p for p in month_dir.glob("*.md") if p.name != "_index.md"]
            )
            lines = [
                f"# Meetings — {anchor_dt.year:04d}-{anchor_dt.month:02d}",
                "",
                f"_{len(md_files)} meetings captured_",
                "",
            ]
            for p in md_files:
                stem = p.stem  # "<id>-<slug>"
                lines.append(f"- [[{stem}]]")
            (month_dir / "_index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception as exc:
            logger.debug("vault_index_write_failed", error=str(exc))


@lru_cache()
def get_meeting_vault_writer() -> MeetingVaultWriter:
    return MeetingVaultWriter()
