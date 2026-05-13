"""
TokenJuice — deterministic tool-output compaction.

Inspired by https://github.com/vincentkoc/tokenjuice (MIT). Re-implemented for
Zero so tool results don't dump tens of kilobytes of HTML/terminal cruft into
the LLM context window. Goal: cut tokens by 50-90% on typical scrape / git /
search / file-read outputs while preserving the semantically useful bits.

Rules (applied in order):

1. **HTML → Markdown**: drop <script>, <style>, <noscript>; collapse <div>/<span>
   wrappers; convert headings, lists, links, code. No deps — small regex pass
   designed for "good-enough" not "perfect HTML parsing".
2. **URL shortening**: long URLs (>80 chars) become ``<host/…>`` placeholders
   indexed in a footnote section. The LLM never needs the full URL inline.
3. **Terminal-noise stripping**: ANSI escape codes, carriage-return progress
   bars, spinner repeats, trailing whitespace.
4. **Block dedup**: collapse runs of identical consecutive lines to a single
   "(x N)" marker.
5. **Tail-only large payloads**: if a block is over ``max_chars``, keep the
   first ``head`` chars and last ``tail`` chars with a ``[…trimmed N chars…]``
   marker.

Public API stays narrow on purpose:

    compact(text, *, kind="auto", max_chars=8000) -> str
    estimate_savings(before, after) -> dict

The kind hint (``html`` / ``terminal`` / ``json`` / ``text`` / ``auto``) only
biases which rules run; the safe path is ``auto``, which is what every caller
should use unless they already know the type.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

__all__ = ["compact", "estimate_savings", "CompactionReport"]


# Approximate tokens-per-character ratio for typical English / code text.
# Real tokenizers vary 3-5 chars/token; we use 4 as a fair middle for telemetry.
_CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class CompactionReport:
    """What `compact` did. Useful for logging / dashboards."""

    before_chars: int
    after_chars: int
    before_tokens_est: int
    after_tokens_est: int
    savings_ratio: float  # 0..1, how much we cut


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
_CR_BAR_RE = re.compile(r"^[^\n]*\r")  # progress bars overwrite the same line
_TRAILING_WS_RE = re.compile(r"[ \t]+$", flags=re.MULTILINE)
_BLANK_RUN_RE = re.compile(r"\n{3,}")
_URL_RE = re.compile(r"https?://[^\s\)\]<>\"']+")

# HTML — small, deliberately not a full parser.
_SCRIPT_STYLE_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", flags=re.IGNORECASE | re.DOTALL)
_COMMENT_RE = re.compile(r"<!--.*?-->", flags=re.DOTALL)
_TAG_OPEN_CLOSE_RE = re.compile(r"<(/?)(\w+)([^>]*)>")
_ATTR_RE = re.compile(r"(\w+)\s*=\s*\"([^\"]*)\"")
_HEADING_RE = re.compile(r"<h([1-6])[^>]*>(.*?)</h\1>", flags=re.IGNORECASE | re.DOTALL)
_LINK_RE = re.compile(r"<a\b[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", flags=re.IGNORECASE | re.DOTALL)
_LI_RE = re.compile(r"<li[^>]*>(.*?)</li>", flags=re.IGNORECASE | re.DOTALL)
_BR_RE = re.compile(r"<br\s*/?>", flags=re.IGNORECASE)
_P_RE = re.compile(r"</p>", flags=re.IGNORECASE)
_CODE_RE = re.compile(r"<code[^>]*>(.*?)</code>", flags=re.IGNORECASE | re.DOTALL)
_PRE_RE = re.compile(r"<pre[^>]*>(.*?)</pre>", flags=re.IGNORECASE | re.DOTALL)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")


def _looks_like_html(text: str) -> bool:
    sample = text[:4096].lower()
    if "<html" in sample or "<!doctype html" in sample:
        return True
    if sample.count("<") > 10 and sample.count(">") > 10 and ("</" in sample):
        return True
    return False


def _looks_like_terminal(text: str) -> bool:
    if "\x1b[" in text[:4096]:
        return True
    if "\r" in text[:4096] and text[:4096].count("\r") > 2:
        return True
    return False


def _looks_like_json(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith("{") or stripped.startswith("[")


def _html_to_markdown(text: str) -> str:
    out = _SCRIPT_STYLE_RE.sub("", text)
    out = _COMMENT_RE.sub("", out)
    out = _PRE_RE.sub(lambda m: f"\n```\n{m.group(1).strip()}\n```\n", out)
    out = _CODE_RE.sub(lambda m: f"`{m.group(1).strip()}`", out)
    out = _HEADING_RE.sub(lambda m: f"\n{'#' * int(m.group(1))} {_TAG_STRIP_RE.sub('', m.group(2)).strip()}\n", out)
    out = _LINK_RE.sub(lambda m: f"[{_TAG_STRIP_RE.sub('', m.group(2)).strip()}]({m.group(1)})", out)
    out = _LI_RE.sub(lambda m: f"\n- {_TAG_STRIP_RE.sub('', m.group(1)).strip()}", out)
    out = _BR_RE.sub("\n", out)
    out = _P_RE.sub("\n\n", out)
    out = _TAG_STRIP_RE.sub("", out)
    # HTML entities — the ones that bloat token counts the most.
    out = (
        out.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    return out


def _strip_terminal_noise(text: str) -> str:
    out = _ANSI_RE.sub("", text)
    # Collapse "x\rx\rx\rfinal" progress bars to just "final".
    # Splitlines treats \r alone as a line break in Python, so split on \n only
    # then collapse any \r sequence inside each line to the last segment.
    lines: list[str] = []
    for line in out.split("\n"):
        if "\r" in line:
            line = line.rsplit("\r", 1)[-1]
        lines.append(line)
    return "\n".join(lines)


def _shorten_urls(text: str, threshold: int = 80) -> tuple[str, list[str]]:
    """Replace long URLs with ``<host/…N>`` and return a footnote list."""
    notes: list[str] = []
    seen: dict[str, str] = {}

    def repl(match: re.Match) -> str:
        url = match.group(0)
        if len(url) < threshold:
            return url
        if url in seen:
            return seen[url]
        host = url.split("/", 3)[2] if "://" in url else url[:20]
        marker = f"<{host}/…{len(notes) + 1}>"
        notes.append(f"[{len(notes) + 1}]: {url}")
        seen[url] = marker
        return marker

    return _URL_RE.sub(repl, text), notes


def _dedup_runs(text: str) -> str:
    out: list[str] = []
    prev: Optional[str] = None
    count = 0
    for line in text.splitlines():
        if prev is not None and line.strip() == prev.strip() and line.strip():
            count += 1
            continue
        if count > 0:
            out.append(f"  (x {count + 1})")
            count = 0
        out.append(line)
        prev = line
    if count > 0:
        out.append(f"  (x {count + 1})")
    return "\n".join(out)


def _trim_oversized(text: str, max_chars: int, head: int = 2000, tail: int = 1500) -> str:
    if len(text) <= max_chars:
        return text
    trimmed = len(text) - (head + tail)
    return f"{text[:head]}\n\n[…trimmed {trimmed} chars…]\n\n{text[-tail:]}"


def _normalize_whitespace(text: str) -> str:
    out = _TRAILING_WS_RE.sub("", text)
    out = _BLANK_RUN_RE.sub("\n\n", out)
    return out.strip()


def compact(
    text: str,
    *,
    kind: str = "auto",
    max_chars: int = 8000,
) -> str:
    """Compact a tool output string to roughly half its size or less.

    Args:
        text: raw tool output (HTML, terminal, JSON, free text)
        kind: "auto" | "html" | "terminal" | "json" | "text"
        max_chars: hard cap; oversized payloads get head+tail with ellipsis

    Returns:
        compacted text, plus a "Links" footnote section if URLs were shortened.
    """
    if not text:
        return text

    if kind == "auto":
        if _looks_like_html(text):
            kind = "html"
        elif _looks_like_terminal(text):
            kind = "terminal"
        elif _looks_like_json(text):
            kind = "json"
        else:
            kind = "text"

    out = text

    if kind == "html":
        out = _html_to_markdown(out)
    elif kind == "terminal":
        out = _strip_terminal_noise(out)
    elif kind == "json":
        # Re-emit compact JSON; preserves semantics, saves bytes.
        try:
            out = json.dumps(json.loads(out), separators=(",", ":"))
        except (ValueError, TypeError):
            pass  # not actually JSON, fall through

    out, footnotes = _shorten_urls(out)
    out = _normalize_whitespace(out)
    out = _dedup_runs(out)
    out = _trim_oversized(out, max_chars=max_chars)

    if footnotes:
        out += "\n\n## Links\n" + "\n".join(footnotes)

    return out


def estimate_savings(before: str, after: str) -> CompactionReport:
    """Return a small report on how much `compact` saved."""
    bc = len(before)
    ac = len(after)
    bt = max(1, bc // _CHARS_PER_TOKEN)
    at = max(1, ac // _CHARS_PER_TOKEN)
    ratio = 1.0 - (ac / bc) if bc else 0.0
    return CompactionReport(
        before_chars=bc,
        after_chars=ac,
        before_tokens_est=bt,
        after_tokens_est=at,
        savings_ratio=max(0.0, min(1.0, ratio)),
    )
