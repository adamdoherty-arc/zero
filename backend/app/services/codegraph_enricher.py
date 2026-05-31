"""Audit-87: codegraph prompt enrichment for UnifiedLLMClient.

Zero mirror of Legion's Audit-85 (see Legion `.claude/rules/55-codegraph.md`).
Before every LLM call leaves the backend, this service extracts symbol / file
hints from the prompt and asks codegraph for a compact composed context block,
which it prepends to the system prompt as
`<codegraph_context>…</codegraph_context>`. Goal: make every Bifrost / vLLM /
shared-router call codegraph-aware without each caller knowing about MCP.

Design notes
------------
- In-container transport is the host-side codegraph-bridge HTTP service.
  Set `CODEGRAPH_HTTP_URL=http://host.docker.internal:18900` in
  docker-compose so the enricher inside the container hits the bridge
  (`GET /context?project=zero&topic=<hint>`). Without the bridge the call
  still proceeds — enrichment just records `status='unavailable'`.
- Unlike Legion, Zero has no `app/api/endpoints/codegraph` proxy, so the
  local-MCP fallback no-ops (returns None) and the HTTP bridge is the sole
  transport. Kept structurally identical so the two services stay in sync.
- LRU cache keyed by `(source, sha1(prompt[:512] + sys[:256]))` with a
  120-second TTL. Most Zero LLM calls repeat similar prompts within short
  windows (brief composition, periodic auditor runs).
- Hard caps: max 2 hints per call, ≤2 000 tokens added (1 token ≈ 4 chars).
- Skips silently (`status='skipped'`) for sources that would loop or don't
  benefit: embeddings, the enricher itself, health probes.
- Graceful degradation: any codegraph error → returns the prompt untouched
  with `status='unavailable'`. The LLM call must NEVER fail because
  enrichment failed.

Env knobs
---------
ZERO_CODEGRAPH_ENRICHER: "true"/"false" (default "true"). Hard kill.
ZERO_CODEGRAPH_ENRICHER_MAX_TOKENS: int (default 2000).
CODEGRAPH_HTTP_URL: host bridge base URL (e.g. http://host.docker.internal:18900).
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


# Skip sources that would either loop (codegraph touching codegraph) or
# don't benefit from code context (embeddings, health). Match by prefix.
_SKIP_SOURCE_PREFIXES: tuple[str, ...] = (
    "codegraph_enricher",
    "embedding",
    "embed",
    "health",
    "livez",
    "warmup",
    "provider_probe",
)

_DEFAULT_MAX_TOKENS = int(os.getenv("ZERO_CODEGRAPH_ENRICHER_MAX_TOKENS", "2000"))
_CACHE_TTL_S = 120.0
_CACHE_MAX_ENTRIES = 256

# Symbol-hint extraction. Order matters — first match wins per regex.
# Backticked identifiers are the highest-quality hint because callers
# usually mean "lookup this exact symbol".
_RE_BACKTICK = re.compile(r"`([A-Za-z_][A-Za-z0-9_]{2,})`")
_RE_CLASS_DEF = re.compile(r"\bclass\s+([A-Z][A-Za-z0-9_]+)")
_RE_PY_FN = re.compile(r"\bdef\s+([A-Za-z_][A-Za-z0-9_]+)")
_RE_TS_FN = re.compile(r"\bfunction\s+([A-Za-z_][A-Za-z0-9_]+)")
_RE_FILEPATH = re.compile(r"([A-Za-z0-9_./-]+\.(?:py|ts|tsx|jsx?|sql))")
_RE_CAMEL_HINT = re.compile(r"\b([A-Z][a-z]+(?:[A-Z][a-z]+){1,4})\b")


# Explicit stoplist for hints that add zero value: generic docstring filler,
# python dunders, literal docstring example paths, common English nouns
# picked up by the CamelCase fallback. Lowercase; comparison is lowercased.
_HINT_STOPLIST: frozenset[str] = frozenset({
    "behavior", "context", "result", "results", "response", "request",
    "example", "value", "values", "config", "settings", "default",
    "input", "output", "data", "info", "type", "name", "kind", "status",
    "__init__", "__name__", "__main__", "__init_subclass__",
    "init", "main", "args", "kwargs",
    "relative", "path/to/file.py", "your_file.py", "example.py",
})


def _is_stoplisted(tok: str) -> bool:
    t = tok.strip().lower()
    if t in _HINT_STOPLIST:
        return True
    if "path/to" in t or "your_" in t:
        return True
    if t.startswith("__") and t.endswith("__"):
        return True
    return False


@dataclass(slots=True)
class EnrichmentResult:
    enriched: bool
    status: str  # ok | no_hints | unavailable | skipped | disabled
    tokens_added: int
    cache_hit: bool
    hints_used: tuple[str, ...]
    new_system_prompt: Optional[str]


def extract_symbol_hints(prompt: str, system_prompt: Optional[str], max_hints: int = 2) -> list[str]:
    """Pick the most likely code symbols / files the LLM will need context for.

    Strategy: collect candidates in priority order (backticks > class > fn >
    filepath > CamelCase), dedupe preserving order, return top N. CamelCase
    is filtered against common stoplist tokens that produce false hits.
    """
    haystack = (system_prompt or "") + "\n" + (prompt or "")
    if len(haystack) < 80:
        return []

    seen: set[str] = set()
    ordered: list[str] = []

    def _push(tok: str) -> None:
        t = tok.strip()
        if not t or len(t) < 3 or t.lower() in seen:
            return
        if _is_stoplisted(t):
            return
        seen.add(t.lower())
        ordered.append(t)

    for m in _RE_BACKTICK.findall(haystack):
        _push(m)
    for m in _RE_CLASS_DEF.findall(haystack):
        _push(m)
    for m in _RE_PY_FN.findall(haystack):
        _push(m)
    for m in _RE_TS_FN.findall(haystack):
        _push(m)
    for m in _RE_FILEPATH.findall(haystack):
        _push(m)
    if len(ordered) < max_hints:
        # CamelCase is noisy — only fill remaining slots from it.
        stop = {
            "TODO", "FIXME", "XXX", "JSON", "YAML", "HTML", "HTTP",
            "API", "URL", "SQL", "CLI", "CSS", "DOM", "GPU", "CPU",
        }
        for m in _RE_CAMEL_HINT.findall(haystack):
            if m.upper() in stop:
                continue
            _push(m)
            if len(ordered) >= max_hints * 3:
                break

    return ordered[:max_hints]


def _approx_tokens(text: str) -> int:
    """Cheap 1-token ≈ 4-char approximation. Good enough for budget gates."""
    return max(1, len(text) // 4)


def _is_disabled() -> bool:
    return os.getenv("ZERO_CODEGRAPH_ENRICHER", "true").strip().lower() in {
        "false", "0", "no", "off",
    }


def _should_skip_source(source: str) -> bool:
    if not source:
        return False
    s = source.lower()
    return any(s.startswith(p) for p in _SKIP_SOURCE_PREFIXES)


class _LRUCache:
    """Tiny TTL-LRU. Async-safe via lock; reads + writes are O(1) amortised."""

    def __init__(self, max_entries: int = _CACHE_MAX_ENTRIES) -> None:
        self._max = max_entries
        self._store: dict[str, tuple[float, EnrichmentResult]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[EnrichmentResult]:
        async with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            ts, val = entry
            if time.monotonic() - ts > _CACHE_TTL_S:
                self._store.pop(key, None)
                return None
            return val

    async def put(self, key: str, val: EnrichmentResult) -> None:
        async with self._lock:
            if len(self._store) >= self._max:
                # FIFO eviction is good enough — this isn't a hot loop.
                self._store.pop(next(iter(self._store)), None)
            self._store[key] = (time.monotonic(), val)


_CACHE = _LRUCache()


def _cache_key(source: str, prompt: str, system_prompt: Optional[str]) -> str:
    h = hashlib.sha1()
    h.update((source or "").encode("utf-8", errors="ignore"))
    h.update(b"\x1f")
    h.update((prompt or "")[:512].encode("utf-8", errors="ignore"))
    h.update(b"\x1f")
    h.update(((system_prompt or "")[:256]).encode("utf-8", errors="ignore"))
    return h.hexdigest()


_HTTP_BRIDGE_URL = os.getenv("CODEGRAPH_HTTP_URL", "").rstrip("/")


async def _fetch_via_http_bridge(hint: str, project: str, timeout: float) -> Optional[str]:
    """Call the host-side codegraph-bridge service (Audit-87).

    Used inside Docker containers where `codegraph` is not installed.
    Set `CODEGRAPH_HTTP_URL=http://host.docker.internal:18900` in
    docker-compose.yml to enable.
    """
    try:
        import httpx  # type: ignore
    except Exception:  # pragma: no cover
        return None
    url = f"{_HTTP_BRIDGE_URL}/context"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url, params={"project": project, "topic": hint})
            if r.status_code != 200:
                return None
            data = r.json()
            return str(data.get("text") or "") or None
    except Exception as exc:  # noqa: BLE001
        logger.debug("codegraph_enricher_bridge_failed", url=url, error=str(exc))
        return None


async def _fetch_via_local_mcp(hint: str, timeout: float) -> Optional[str]:
    """Host-native fallback. Zero has no `/api/codegraph/*` proxy, so this
    returns None — kept to mirror Legion's enricher structure 1:1."""
    return None


async def _fetch_codegraph_context(hint: str, timeout: float = 8.0, project: str = "zero") -> Optional[str]:
    """Pick the best transport. HTTP bridge wins when configured."""
    if _HTTP_BRIDGE_URL:
        result = await _fetch_via_http_bridge(hint, project, timeout)
        if result is not None:
            return result
    return await _fetch_via_local_mcp(hint, timeout)


def _format_block(hints_used: list[str], chunks: list[str], budget_tokens: int) -> tuple[str, int]:
    """Stitch hint chunks into one block under the token budget."""
    body_lines: list[str] = []
    used_tokens = 0
    budget = budget_tokens
    for hint, chunk in zip(hints_used, chunks):
        if not chunk:
            continue
        # Reserve ~30 tokens per heading + trailer
        header = f"\n### {hint}\n"
        candidate = header + chunk.strip() + "\n"
        cost = _approx_tokens(candidate)
        if used_tokens + cost > budget:
            # Trim chunk to fit remaining budget; never write zero-trimmed.
            remaining = max(0, budget - used_tokens - _approx_tokens(header) - 8)
            if remaining < 40:
                break
            trimmed = chunk.strip()[: remaining * 4]
            candidate = header + trimmed + "\n…[truncated by enricher budget]\n"
            body_lines.append(candidate)
            used_tokens = budget
            break
        body_lines.append(candidate)
        used_tokens += cost
    if not body_lines:
        return "", 0
    block = (
        "<codegraph_context source=\"codegraph_enricher\">\n"
        + "".join(body_lines)
        + "</codegraph_context>"
    )
    return block, _approx_tokens(block)


async def enrich(
    prompt: str,
    system_prompt: Optional[str],
    source: str = "",
    project: str = "zero",
    budget_tokens: int = _DEFAULT_MAX_TOKENS,
) -> EnrichmentResult:
    """Return an EnrichmentResult; never raises."""
    if _is_disabled():
        return EnrichmentResult(False, "disabled", 0, False, (), None)
    if _should_skip_source(source):
        return EnrichmentResult(False, "skipped", 0, False, (), None)

    key = _cache_key(source, prompt, system_prompt)
    cached = await _CACHE.get(key)
    if cached is not None:
        return EnrichmentResult(
            enriched=cached.enriched,
            status=cached.status,
            tokens_added=cached.tokens_added,
            cache_hit=True,
            hints_used=cached.hints_used,
            new_system_prompt=cached.new_system_prompt,
        )

    hints = extract_symbol_hints(prompt, system_prompt, max_hints=2)
    if not hints:
        res = EnrichmentResult(False, "no_hints", 0, False, (), None)
        await _CACHE.put(key, res)
        return res

    chunks: list[str] = []
    used_hints: list[str] = []
    for h in hints:
        chunk = await _fetch_codegraph_context(h, project=project)
        if chunk:
            chunks.append(chunk)
            used_hints.append(h)
        if sum(_approx_tokens(c) for c in chunks) >= budget_tokens:
            break

    if not chunks:
        res = EnrichmentResult(False, "unavailable", 0, False, tuple(hints), None)
        await _CACHE.put(key, res)
        return res

    block, added_tokens = _format_block(used_hints, chunks, budget_tokens)
    if not block:
        res = EnrichmentResult(False, "no_hints", 0, False, tuple(hints), None)
        await _CACHE.put(key, res)
        return res

    new_sys = (block + "\n\n" + system_prompt) if system_prompt else block
    res = EnrichmentResult(
        enriched=True,
        status="ok",
        tokens_added=added_tokens,
        cache_hit=False,
        hints_used=tuple(used_hints),
        new_system_prompt=new_sys,
    )
    await _CACHE.put(key, res)
    logger.debug(
        "codegraph_enricher_ok", source=source, hints=list(used_hints),
        tokens_added=added_tokens,
    )
    return res


def _split_messages(messages: List[Dict[str, str]]) -> tuple[Optional[int], str, str]:
    """Locate the system message (if any) and concatenate user content.

    Returns (system_index_or_None, system_text, user_text). Zero assembles
    chat as a list of {role, content} dicts, so the enricher operates on the
    system message in place rather than a standalone system_prompt string.
    """
    sys_idx: Optional[int] = None
    sys_text = ""
    user_parts: list[str] = []
    for i, m in enumerate(messages or []):
        role = (m.get("role") or "").lower()
        content = m.get("content") or ""
        if role == "system" and sys_idx is None:
            sys_idx = i
            sys_text = content
        elif role in ("user", "human"):
            user_parts.append(content)
    return sys_idx, sys_text, "\n".join(user_parts)


async def enrich_messages(
    messages: List[Dict[str, str]],
    source: str = "",
    project: str = "zero",
) -> EnrichmentResult:
    """Adapter for UnifiedLLMClient: enrich the system message of a chat
    `messages` list in place. Never raises — returns the EnrichmentResult so
    the caller can persist codegraph_* observability fields.

    Caller pattern in UnifiedLLMClient._call_provider():

        cg = await codegraph_enricher.enrich_messages(messages, source=task_type, project="zero")
        # messages now carries the <codegraph_context> block on its system msg;
        # downstream LLMUsage row picks up cg.* fields.
    """
    try:
        sys_idx, sys_text, user_text = _split_messages(messages)
        res = await enrich(user_text, sys_text or None, source=source, project=project)
        if not res.enriched or not res.new_system_prompt:
            return res
        if sys_idx is not None:
            messages[sys_idx]["content"] = res.new_system_prompt
        else:
            # No system message present — inject one at the front.
            messages.insert(0, {"role": "system", "content": res.new_system_prompt})
        return res
    except Exception as exc:  # noqa: BLE001 — enrichment must never break a call
        logger.debug("codegraph_enricher_messages_failed", error=str(exc))
        return EnrichmentResult(False, "unavailable", 0, False, (), None)
