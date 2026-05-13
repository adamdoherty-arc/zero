"""
Tool-output helpers that pipe results through TokenJuice automatically.

Use these wrappers anywhere tool output flows into an LLM prompt:

    from app.services.tool_output_helpers import (
        compact_git_diff,
        compact_terminal_output,
        compact_file_read,
        compact_html,
    )

Each helper picks the right ``kind`` for TokenJuice and stamps the call with
a label so the ``/api/llm/compact/metrics`` endpoint can show which call
sites are saving the most tokens.
"""

from __future__ import annotations

from typing import Optional

from app.services.tokenjuice_compactor import compact_with_telemetry

# Files smaller than this don't need compaction — the per-call overhead
# outweighs the savings on short snippets. Tunable per call site.
DEFAULT_MIN_SIZE = 2000


def compact_git_diff(diff: str, *, max_chars: int = 12000, label: str = "git_diff") -> str:
    """Compact ``git diff`` output. Strips noise but keeps hunk headers."""
    if not diff or len(diff) < DEFAULT_MIN_SIZE:
        return diff
    return compact_with_telemetry(diff, kind="terminal", max_chars=max_chars, label=label)


def compact_terminal_output(text: str, *, max_chars: int = 8000, label: str = "terminal") -> str:
    """Compact shell / build / test stdout+stderr — collapses ANSI, progress
    bars, duplicate runs."""
    if not text or len(text) < DEFAULT_MIN_SIZE:
        return text
    return compact_with_telemetry(text, kind="terminal", max_chars=max_chars, label=label)


def compact_file_read(text: str, *, max_chars: int = 12000, min_size: int = DEFAULT_MIN_SIZE,
                      label: Optional[str] = None) -> str:
    """Compact a file's contents before stuffing into an LLM prompt.

    Auto-detects HTML vs plain text. Files below ``min_size`` chars pass
    through unchanged.
    """
    if not text or len(text) < min_size:
        return text
    return compact_with_telemetry(text, kind="auto", max_chars=max_chars, label=label or "file_read")


def compact_html(html: str, *, max_chars: int = 12000, label: str = "html") -> str:
    """Compact raw HTML into Markdown. Drops scripts/styles, shortens URLs."""
    if not html:
        return html
    return compact_with_telemetry(html, kind="html", max_chars=max_chars, label=label)


def compact_json_dump(text: str, *, max_chars: int = 8000, label: str = "json") -> str:
    """Compact a JSON-shaped string by re-emitting it without indentation."""
    if not text:
        return text
    return compact_with_telemetry(text, kind="json", max_chars=max_chars, label=label)
