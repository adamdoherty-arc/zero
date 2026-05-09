"""
Vault Writer Service — filesystem-direct writes to the Obsidian vault.

This is the Phase 0 bridge implementation. It writes directly to the vault
path mounted at ZERO_VAULT_PATH (default /vault, mapped to
C:\\code\\vault\\ObsidianZero on the Windows host).

Phase 2 of the SecondBrain plan replaces this with the cyanheads Obsidian MCP
for append/patch-heading operations that respect Obsidian's Local REST API.
Until then, we write whole files under the agent-owned `_agent/` namespace,
which is explicitly greenfield per the vault constitution.

Contract (from 00_Meta/CLAUDE.md):
  - Never touch .obsidian/, .git/, .trash/
  - Free-write only under 00_Meta/_agent/**
  - Always append an agent-run-id footer
  - Append-only for human-owned notes (this service does not modify them)
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import structlog

from app.infrastructure.config import get_settings

logger = structlog.get_logger(__name__)


_FORBIDDEN_SEGMENTS = {".obsidian", ".git", ".trash"}
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(value: str, max_len: int = 60) -> str:
    s = _SLUG_RE.sub("-", value.lower()).strip("-")
    return s[:max_len] or "untitled"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _audit_footer(run_id: str, source: str) -> str:
    return f"\n<!-- agent-run-id: {run_id} source: {source} at: {_now_iso()} -->\n"


class VaultWriterService:
    """Filesystem-direct writer for agent-owned vault paths."""

    def __init__(self, vault_root: Optional[str] = None) -> None:
        settings = get_settings()
        self.vault_root = Path(vault_root or settings.vault_path)

    # ------------------------------------------------------------------
    # Availability + safety
    # ------------------------------------------------------------------

    def available(self) -> bool:
        """True when the vault volume is mounted and writable."""
        return self.vault_root.is_dir() and os.access(self.vault_root, os.W_OK)

    def _resolve_safe(self, relative: str) -> Path:
        rel = Path(relative)
        if rel.is_absolute():
            raise ValueError(f"vault paths must be relative: {relative!r}")
        parts = rel.parts
        for seg in parts:
            if seg in _FORBIDDEN_SEGMENTS:
                raise ValueError(f"forbidden path segment in vault write: {seg!r}")
            if seg == "..":
                raise ValueError("path traversal in vault write")
        target = (self.vault_root / rel).resolve()
        root = self.vault_root.resolve()
        if root not in target.parents and target != root:
            raise ValueError(f"vault path escapes root: {target}")
        return target

    # ------------------------------------------------------------------
    # Low-level write (agent namespace)
    # ------------------------------------------------------------------

    def write_agent_file(
        self,
        relative_path: str,
        content: str,
        *,
        source: str = "zero",
        run_id: Optional[str] = None,
        overwrite: bool = True,
    ) -> dict[str, Any]:
        """Write a full file under 00_Meta/_agent/ (or any agent-owned subtree).

        Returns a dict with the absolute path, size, and sha256 hash.
        """
        if not self.available():
            raise RuntimeError(f"vault not available at {self.vault_root}")

        rel = Path(relative_path)
        if rel.parts[:2] != ("00_Meta", "_agent"):
            raise ValueError(
                "write_agent_file only writes under 00_Meta/_agent/**"
            )

        target = self._resolve_safe(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not overwrite:
            raise FileExistsError(f"refusing to overwrite {target}")

        run = run_id or uuid.uuid4().hex[:12]
        body = content.rstrip() + _audit_footer(run, source)
        target.write_text(body, encoding="utf-8")
        sha = hashlib.sha256(body.encode("utf-8")).hexdigest()

        logger.info(
            "vault_write",
            path=str(target.relative_to(self.vault_root)),
            bytes=len(body),
            sha=sha[:12],
            source=source,
            run_id=run,
        )
        return {
            "path": str(target),
            "relative": str(target.relative_to(self.vault_root)),
            "sha256": sha,
            "bytes": len(body),
            "run_id": run,
        }

    # ------------------------------------------------------------------
    # Loop run output (cross-project self-improvement framework)
    # ------------------------------------------------------------------

    def write_loop_run(
        self,
        *,
        loop_name: str,
        run_id: int,
        owner_project: str,
        runner_kind: str,
        status: str,
        started_at: datetime,
        ended_at: Optional[datetime] = None,
        duration_s: Optional[float] = None,
        judge_score: Optional[float] = None,
        variant_label: Optional[str] = None,
        cost_tokens: Optional[int] = None,
        output: str = "",
        error: Optional[str] = None,
    ) -> dict[str, Any]:
        """Write one loop run as a markdown report under 00_Meta/_agent/loops/<name>/runs/.

        Durable visibility: this file persists even if Zero, Legion, and Postgres
        are all down. The /loops UI renders these via vault retrieval when the DB
        is available; the user can also browse them directly in Obsidian.
        """
        ts = started_at.strftime("%Y-%m-%d-%H%M%S") if started_at else _today_str()
        safe_name = _slug(loop_name, max_len=80)
        relative = f"00_Meta/_agent/loops/{safe_name}/runs/{ts}.md"

        header = [
            "---",
            f"id: loop-run-{run_id}",
            "type: loop_run",
            "partition: personal",
            f"loop: {loop_name}",
            f"loop_run_id: {run_id}",
            f"owner_project: {owner_project}",
            f"runner_kind: {runner_kind}",
            f"status: {status}",
            f"started_at: {started_at.isoformat() if started_at else ''}",
        ]
        if ended_at:
            header.append(f"ended_at: {ended_at.isoformat()}")
        if duration_s is not None:
            header.append(f"duration_s: {duration_s:.2f}")
        if judge_score is not None:
            header.append(f"judge_score: {judge_score:.2f}")
        if variant_label:
            header.append(f"variant: {variant_label}")
        if cost_tokens is not None:
            header.append(f"cost_tokens: {cost_tokens}")
        header.extend([
            "agent_writable: []",
            "tags: [loop, agent, auto]",
            "---",
            "",
            f"# Loop run — {loop_name} #{run_id}",
            "",
            f"**Status:** `{status}`",
            "",
        ])
        if error:
            header.extend(["## Error", "", "```", error.strip(), "```", ""])
        if output:
            header.extend(["## Output", "", output.strip(), ""])

        body = "\n".join(header)
        return self.write_agent_file(
            relative_path=relative,
            content=body,
            source=f"loop:{loop_name}",
            run_id=str(run_id),
            overwrite=True,
        )

    def write_loop_index_entry(
        self,
        *,
        loop_name: str,
        run_id: int,
        status: str,
        judge_score: Optional[float],
        started_at: datetime,
        relative_path: str,
    ) -> None:
        """Append one line to today's loop index for a roll-up view."""
        if not self.available():
            return
        today = _today_str()
        index_rel = f"00_Meta/_agent/loops/_index/{today}.md"
        target = self._resolve_safe(index_rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        score_s = f"{judge_score:.1f}" if judge_score is not None else "  - "
        line = (
            f"- {started_at.strftime('%H:%M:%S')} "
            f"`{status:>8}` score={score_s} "
            f"[{loop_name}#{run_id}](../{loop_name.replace(' ', '-')}/runs/{started_at.strftime('%Y-%m-%d-%H%M%S')}.md)"
        )
        if not target.exists():
            target.write_text(
                f"# Loop runs — {today}\n\nOne line per run. Newest at bottom.\n\n",
                encoding="utf-8",
            )
        with target.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    # ------------------------------------------------------------------
    # Research output
    # ------------------------------------------------------------------

    def write_research_report(
        self,
        *,
        topic: str,
        markdown: str,
        executive_summary: str = "",
        sources: Optional[list[str]] = None,
        report_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Write a deep-research report to 00_Meta/_agent/research/YYYY-MM-DD-slug.md."""
        settings = get_settings()
        today = _today_str()
        slug = _slug(topic)
        filename = f"{today}-{slug}.md"

        # Wrap with frontmatter + exec summary header
        header_lines = [
            "---",
            f"id: research-{today}-{slug}",
            "type: research",
            "partition: personal",
            "status: reference",
            f"topic: {topic!r}",
            f"generated: {_now_iso()}",
            f"source: autonomous_research_loop",
        ]
        if report_id:
            header_lines.append(f"report_id: {report_id}")
        header_lines.extend([
            "agent_writable: []",
            "tags: [research, agent, auto]",
            "---",
            "",
            f"# {topic}",
            "",
        ])
        if executive_summary:
            header_lines += ["## Executive Summary", "", executive_summary.strip(), ""]
        if sources:
            header_lines += ["## Sources", ""]
            for s in sources:
                header_lines.append(f"- {s}")
            header_lines.append("")
        header_lines += ["## Report", "", markdown.strip(), ""]

        body = "\n".join(header_lines)
        relative = f"{settings.vault_agent_research_subdir}/{filename}"
        return self.write_agent_file(
            relative_path=relative,
            content=body,
            source="autonomous_research_loop",
            run_id=run_id,
            overwrite=True,
        )

    # ------------------------------------------------------------------
    # Meeting output
    # ------------------------------------------------------------------

    def write_meeting_summary(
        self,
        *,
        meeting_id: str,
        title: str,
        start_time: Optional[datetime] = None,
        duration_seconds: Optional[int] = None,
        summary_text: str,
        key_topics: Optional[list[str]] = None,
        action_items: Optional[list[Any]] = None,
        decisions: Optional[list[Any]] = None,
        transcript: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Write a processed meeting to 00_Meta/_agent/meetings/YYYY-MM-DD-slug.md.

        Saved as a reference record — the database row remains the source of
        truth; this gives the user a human-readable artifact the vault can
        index and link to.
        """
        stamp = start_time.astimezone(timezone.utc) if start_time else datetime.now(timezone.utc)
        date_str = stamp.strftime("%Y-%m-%d")
        slug = _slug(title)
        filename = f"{date_str}-{slug}.md"

        lines: list[str] = [
            "---",
            f"id: meeting-{meeting_id}",
            "type: meeting",
            "partition: personal",
            "status: completed",
            f"title: {title!r}",
            f"started: {stamp.isoformat(timespec='seconds')}",
        ]
        if duration_seconds is not None:
            lines.append(f"duration_seconds: {duration_seconds}")
        lines.extend([
            "agent_writable: []",
            "tags: [meeting, agent, auto]",
            "---",
            "",
            f"# {title}",
            "",
        ])

        if summary_text:
            lines += ["## Summary", "", summary_text.strip(), ""]

        if key_topics:
            lines += ["## Key Topics", ""]
            for topic in key_topics:
                lines.append(f"- {topic}")
            lines.append("")

        if action_items:
            lines += ["## Action Items", ""]
            for item in action_items:
                if isinstance(item, dict):
                    desc = item.get("description") or item.get("action") or ""
                    owner = item.get("owner") or "Unassigned"
                    lines.append(f"- [ ] {desc} (Owner: {owner})")
                else:
                    lines.append(f"- [ ] {item}")
            lines.append("")

        if decisions:
            lines += ["## Decisions", ""]
            for decision in decisions:
                if isinstance(decision, dict):
                    lines.append(f"- {decision.get('description', decision)}")
                else:
                    lines.append(f"- {decision}")
            lines.append("")

        if transcript:
            lines += ["## Transcript", "", transcript.strip(), ""]

        body = "\n".join(lines)
        relative = f"00_Meta/_agent/meetings/{filename}"
        return self.write_agent_file(
            relative_path=relative,
            content=body,
            source="meeting_processing_pipeline",
            run_id=run_id,
            overwrite=True,
        )


_singleton: Optional[VaultWriterService] = None


def get_vault_writer() -> VaultWriterService:
    global _singleton
    if _singleton is None:
        _singleton = VaultWriterService()
    return _singleton
