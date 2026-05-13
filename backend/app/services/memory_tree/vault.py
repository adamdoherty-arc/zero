"""
Filesystem layout for the Obsidian-compatible vault.

Layout (rooted at ``backend/app/data/vault``):

    sources/{source}/L0/{yyyymmdd-HHMMSS}-{slug}.md
    sources/{source}/L1/{yyyymm}-{slug}.md
    sources/{source}/L2/{yyyy}-{slug}.md
    topics/{entity_slug}/{yyyymmdd}-{slug}.md
    global/{yyyymmdd}.md

L0 chunks roll up into L1 summaries (per-month), L1 into L2 (per-year).
``global/`` is a single daily-digest file that summarizes everything that
landed across all sources that day.

Each file has a YAML frontmatter block with metadata: source, level, tags,
created, parent (the chunk it summarises), token_count.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

VAULT_DIRNAME = "vault"

_SLUG_RE = re.compile(r"[^a-zA-Z0-9_-]+")
_FRONT_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)", flags=re.DOTALL)


def slugify(s: str, max_len: int = 64) -> str:
    """Filesystem-safe slug. Keeps the chunk preview useful for Obsidian search."""
    cleaned = _SLUG_RE.sub("-", s.strip().lower()).strip("-")
    return (cleaned or "chunk")[:max_len]


def vault_root(base_data_dir: Path) -> Path:
    return base_data_dir / VAULT_DIRNAME


@dataclass(frozen=True)
class VaultEntry:
    path: Path
    frontmatter: dict
    body: str


def _frontmatter_dump(metadata: dict) -> str:
    lines = ["---"]
    for k, v in metadata.items():
        if v is None:
            continue
        if isinstance(v, list):
            lines.append(f"{k}: [{', '.join(map(str, v))}]")
        else:
            # Quote any value that looks like it could break YAML.
            s = str(v)
            needs_quote = any(c in s for c in [":", "#", "[", "]", "{", "}"])
            if needs_quote and not (s.startswith('"') and s.endswith('"')):
                s = '"' + s.replace('"', '\\"') + '"'
            lines.append(f"{k}: {s}")
    lines.append("---")
    return "\n".join(lines)


def _frontmatter_parse(text: str) -> tuple[dict, str]:
    m = _FRONT_RE.match(text)
    if not m:
        return {}, text
    raw_meta, body = m.group(1), m.group(2)
    meta: dict = {}
    for line in raw_meta.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip()
        if v.startswith('"') and v.endswith('"'):
            v = v[1:-1]
        meta[k] = v
    return meta, body.strip()


def write_chunk(
    root: Path,
    *,
    source: str,
    level: int,
    title: str,
    body: str,
    tags: Optional[Iterable[str]] = None,
    parent: Optional[str] = None,
    extra_meta: Optional[dict] = None,
) -> Path:
    """Write a chunk file under ``sources/{source}/L{level}/``.

    Returns the absolute path written.
    """
    now = datetime.utcnow()
    dirpath = root / "sources" / slugify(source) / f"L{level}"
    dirpath.mkdir(parents=True, exist_ok=True)
    if level == 0:
        ts = now.strftime("%Y%m%d-%H%M%S")
    elif level == 1:
        ts = now.strftime("%Y%m")
    else:
        ts = now.strftime("%Y")
    filename = f"{ts}-{slugify(title)}.md"
    path = dirpath / filename
    meta = {
        "source": source,
        "level": level,
        "title": title,
        "created": now.isoformat(timespec="seconds") + "Z",
        "tags": list(tags) if tags else [],
        "parent": parent,
        "token_count": len(body) // 4,
    }
    if extra_meta:
        meta.update(extra_meta)
    path.write_text(
        _frontmatter_dump(meta) + "\n\n" + body.strip() + "\n",
        encoding="utf-8",
    )
    return path


def write_topic(
    root: Path,
    *,
    entity: str,
    title: str,
    body: str,
    tags: Optional[Iterable[str]] = None,
    extra_meta: Optional[dict] = None,
) -> Path:
    now = datetime.utcnow()
    dirpath = root / "topics" / slugify(entity)
    dirpath.mkdir(parents=True, exist_ok=True)
    ts = now.strftime("%Y%m%d")
    path = dirpath / f"{ts}-{slugify(title)}.md"
    meta = {
        "type": "topic",
        "entity": entity,
        "title": title,
        "created": now.isoformat(timespec="seconds") + "Z",
        "tags": list(tags) if tags else [],
        "token_count": len(body) // 4,
    }
    if extra_meta:
        meta.update(extra_meta)
    path.write_text(
        _frontmatter_dump(meta) + "\n\n" + body.strip() + "\n",
        encoding="utf-8",
    )
    return path


def write_global_digest(
    root: Path,
    *,
    day: Optional[datetime] = None,
    title: str = "Daily digest",
    body: str,
    sources: Optional[Iterable[str]] = None,
) -> Path:
    when = day or datetime.utcnow()
    dirpath = root / "global"
    dirpath.mkdir(parents=True, exist_ok=True)
    path = dirpath / f"{when.strftime('%Y%m%d')}.md"
    meta = {
        "type": "global",
        "title": title,
        "created": when.isoformat(timespec="seconds") + "Z",
        "sources": list(sources) if sources else [],
        "token_count": len(body) // 4,
    }
    path.write_text(
        _frontmatter_dump(meta) + "\n\n" + body.strip() + "\n",
        encoding="utf-8",
    )
    return path


def read_entry(path: Path) -> Optional[VaultEntry]:
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    meta, body = _frontmatter_parse(text)
    return VaultEntry(path=path, frontmatter=meta, body=body)


def list_entries(root: Path, *, source: Optional[str] = None, entity: Optional[str] = None,
                 scope: Optional[str] = None) -> list[VaultEntry]:
    """Walk the vault and return all matching entries.

    ``scope`` is one of "source", "topic", "global" — if set, the source /
    entity filters apply within that scope.
    """
    if not root.exists():
        return []
    entries: list[VaultEntry] = []
    if scope in (None, "source"):
        src_root = root / "sources"
        if src_root.exists():
            for src_dir in src_root.iterdir():
                if not src_dir.is_dir():
                    continue
                if source and src_dir.name != slugify(source):
                    continue
                for path in src_dir.rglob("*.md"):
                    entry = read_entry(path)
                    if entry:
                        entries.append(entry)
    if scope in (None, "topic"):
        topic_root = root / "topics"
        if topic_root.exists():
            for ent_dir in topic_root.iterdir():
                if not ent_dir.is_dir():
                    continue
                if entity and ent_dir.name != slugify(entity):
                    continue
                for path in ent_dir.glob("*.md"):
                    entry = read_entry(path)
                    if entry:
                        entries.append(entry)
    if scope in (None, "global"):
        global_root = root / "global"
        if global_root.exists():
            for path in global_root.glob("*.md"):
                entry = read_entry(path)
                if entry:
                    entries.append(entry)
    return entries
