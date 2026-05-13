"""
Microagents — small triggered prompts that load when a keyword appears.

Adopted from the OpenHands microagents convention. A microagent is a
Markdown file with YAML frontmatter:

    ---
    name: reachy-motion
    type: knowledge
    triggers: [reachy, antennas, motion, emotion, dance]
    agent: any
    ---

    When Reachy needs to express something physical, prefer the
    motion library at backend/app/services/reachy_motion_library.py.
    81 emotion clips, 19 dances, each with semantic aliases.

Two scopes:

  • **Public microagents** (``microagents/``) — available to every agent.
  • **Repo-scoped microagents** (``.openhands/microagents/``) — apply only
    to this repo. Mirrors the OpenHands ``.openhands/microagents/``
    convention so PRs that drop a file there work automatically.

The service has one method any system-prompt assembler needs:

    ``compose_context_for(text)`` → str

It runs every loaded microagent's trigger list against ``text`` and
concatenates the bodies of the ones that match. Stable order, dedup by
file path, capped at ``MAX_INJECT_CHARS`` so it never blows the context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

import structlog

logger = structlog.get_logger(__name__)


_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)", flags=re.DOTALL)
_PUBLIC_ROOT = Path(__file__).resolve().parents[3] / "microagents"
_REPO_ROOT = Path(__file__).resolve().parents[3] / ".openhands" / "microagents"
MAX_INJECT_CHARS = 4000


@dataclass
class Microagent:
    name: str
    type: str  # "knowledge" | "workflow" | "rules"
    triggers: list[str]
    body: str
    path: Path
    agent: str = "any"  # which agent persona this targets (or "any")

    def matches(self, text: str) -> bool:
        if not text or not self.triggers:
            return False
        lower = text.lower()
        return any(t.lower() in lower for t in self.triggers)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    raw_meta, body = m.group(1), m.group(2).strip()
    meta: dict = {}
    current_key: Optional[str] = None
    list_buf: Optional[list] = None
    for line in raw_meta.splitlines():
        if not line.strip():
            continue
        if line.startswith("  -") or line.startswith("- "):
            value = line.lstrip("- ").strip()
            if list_buf is not None:
                list_buf.append(value)
            continue
        if ":" in line:
            # New top-level key. Flush any pending list.
            if list_buf is not None and current_key is not None:
                meta[current_key] = list_buf
                list_buf = None
            k, _, v = line.partition(":")
            k = k.strip()
            v = v.strip()
            if v == "" or v == "[":
                current_key = k
                list_buf = []
                continue
            # Inline list: [a, b, c]
            if v.startswith("[") and v.endswith("]"):
                items = [x.strip().strip("\"'") for x in v[1:-1].split(",") if x.strip()]
                meta[k] = items
                current_key = None
                list_buf = None
                continue
            meta[k] = v.strip("\"'")
            current_key = None
            list_buf = None
    if list_buf is not None and current_key is not None:
        meta[current_key] = list_buf
    return meta, body


def load_microagent(path: Path) -> Optional[Microagent]:
    if not path.exists() or path.suffix != ".md":
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("microagent_read_failed", path=str(path), error=str(e))
        return None
    meta, body = _parse_frontmatter(raw)
    name = meta.get("name") or path.stem
    triggers = meta.get("triggers") or []
    if isinstance(triggers, str):
        triggers = [triggers]
    return Microagent(
        name=name,
        type=str(meta.get("type", "knowledge")),
        triggers=[str(t) for t in triggers],
        body=body,
        path=path,
        agent=str(meta.get("agent", "any")),
    )


def discover_microagents(roots: Iterable[Path]) -> list[Microagent]:
    agents: list[Microagent] = []
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for path in sorted(root.glob("*.md")):
            mt = load_microagent(path)
            if mt is not None:
                agents.append(mt)
    return agents


@dataclass
class MicroagentMatch:
    name: str
    type: str
    body: str
    path: str


class MicroagentsService:
    def __init__(self) -> None:
        # Read roots at call time so tests can monkeypatch.
        import app.services.microagents_service as _self_mod
        self._roots = [_self_mod._PUBLIC_ROOT, _self_mod._REPO_ROOT]

    def list_all(self) -> list[dict]:
        items = []
        for agent in discover_microagents(self._roots):
            items.append({
                "name": agent.name,
                "type": agent.type,
                "triggers": list(agent.triggers),
                "agent": agent.agent,
                "path": str(agent.path),
                "body_preview": agent.body[:200],
            })
        return items

    def match(
        self, text: str, *, agent_persona: str = "any"
    ) -> list[MicroagentMatch]:
        """Return every microagent whose triggers match ``text``.

        Filters by ``agent_persona`` (microagents declaring ``agent: any``
        always match; otherwise the field must equal the persona).
        """
        out: list[MicroagentMatch] = []
        seen: set[str] = set()
        for agent in discover_microagents(self._roots):
            if agent.agent not in ("any", agent_persona) and agent_persona != "any":
                continue
            if not agent.matches(text):
                continue
            if str(agent.path) in seen:
                continue
            seen.add(str(agent.path))
            out.append(
                MicroagentMatch(
                    name=agent.name,
                    type=agent.type,
                    body=agent.body,
                    path=str(agent.path),
                )
            )
        return out

    def compose_context_for(
        self, text: str, *, agent_persona: str = "any", max_chars: int = MAX_INJECT_CHARS
    ) -> str:
        """Compose a single string fragment ready to inject into a system
        prompt. Returns the empty string when no microagent matches.
        """
        matches = self.match(text, agent_persona=agent_persona)
        if not matches:
            return ""
        parts: list[str] = ["## Active microagents\n"]
        running = len(parts[0])
        for m in matches:
            block = f"### {m.name} ({m.type})\n{m.body.strip()}\n"
            if running + len(block) > max_chars:
                parts.append("\n_(microagent context trimmed)_\n")
                break
            parts.append(block)
            running += len(block)
        return "\n".join(parts).strip()


@lru_cache(maxsize=1)
def get_microagents_service() -> MicroagentsService:
    return MicroagentsService()
