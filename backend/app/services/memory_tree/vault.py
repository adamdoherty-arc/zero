"""
Filesystem layout for the Obsidian-compatible Memory Vault.

The production root is owned by ``MemoryTreeService`` and lives under the
canonical Obsidian mount:

    /vault/00_Meta/_agent/memory_vault/

Test callers may still pass a temporary base directory; in that case the root
is ``<tmp>/vault``. All writers add audit metadata and filename entropy so
multi-chunk writes cannot overwrite each other.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

VAULT_DIRNAME = "vault"

_SLUG_RE = re.compile(r"[^a-zA-Z0-9_-]+")
_FRONT_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)", flags=re.DOTALL)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso_z(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


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


def _audit_footer(run_id: str, source: str) -> str:
    return f"\n<!-- agent-run-id: {run_id} source: {source} -->\n"


def _base_metadata(*, created: str, run_id: str) -> dict:
    return {
        "partition": "personal",
        "created": created,
        "agent_run_id": run_id,
        "agent_writable": [],
    }


def _body_hash(body: str, *, extra: str = "") -> str:
    raw = f"{body}\n{extra}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:10]


def _unique_path(dirpath: Path, filename: str) -> Path:
    path = dirpath / filename
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for _ in range(20):
        candidate = dirpath / f"{stem}-{uuid.uuid4().hex[:8]}{suffix}"
        if not candidate.exists():
            return candidate
    return dirpath / f"{stem}-{uuid.uuid4().hex}{suffix}"


def _write_text(path: Path, text: str, *, root: Path, source: str, run_id: str) -> None:
    """Write through VaultWriterService when this is the real Obsidian vault.

    Unit tests use temporary roots that are not mounted at /vault; those writes
    stay direct but retain the same audit footer.
    """
    try:
        from app.services.vault_writer_service import get_vault_writer

        writer = get_vault_writer()
        vault_root_path = writer.vault_root.resolve()
        resolved = path.resolve()
        if writer.available() and (
            resolved == vault_root_path or vault_root_path in resolved.parents
        ):
            relative = resolved.relative_to(vault_root_path)
            writer.write_agent_file(
                str(relative),
                text,
                source=source,
                run_id=run_id,
                overwrite=False,
            )
            return
    except Exception:
        pass

    root.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + _audit_footer(run_id, source), encoding="utf-8")


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
    now = _now_utc()
    run_id = uuid.uuid4().hex[:12]
    dirpath = root / "sources" / slugify(source) / f"L{level}"
    dirpath.mkdir(parents=True, exist_ok=True)
    if level == 0:
        ts = now.strftime("%Y%m%d-%H%M%S-%f")
    elif level == 1:
        ts = now.strftime("%Y%m")
    else:
        ts = now.strftime("%Y")
    part = (extra_meta or {}).get("part")
    part_suffix = f"-p{int(part):03d}" if isinstance(part, int) else ""
    digest = _body_hash(body, extra=f"{source}:{level}:{title}:{part}:{now.isoformat()}")
    filename = f"{ts}{part_suffix}-{slugify(title)}-{digest}.md"
    path = _unique_path(dirpath, filename)
    created = _iso_z(now)
    meta = {
        **_base_metadata(created=created, run_id=run_id),
        "type": "memory_vault_chunk",
        "source": source,
        "level": level,
        "title": title,
        "tags": list(tags) if tags else [],
        "parent": parent,
        "token_count": len(body) // 4,
    }
    if extra_meta:
        meta.update(extra_meta)
    text = _frontmatter_dump(meta) + "\n\n" + body.strip() + "\n"
    _write_text(path, text, root=root, source=f"memory_vault:{source}", run_id=run_id)
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
    now = _now_utc()
    run_id = uuid.uuid4().hex[:12]
    dirpath = root / "topics" / slugify(entity)
    dirpath.mkdir(parents=True, exist_ok=True)
    ts = now.strftime("%Y%m%d-%H%M%S-%f")
    digest = _body_hash(body, extra=f"{entity}:{title}:{now.isoformat()}")
    path = _unique_path(dirpath, f"{ts}-{slugify(title)}-{digest}.md")
    created = _iso_z(now)
    meta = {
        **_base_metadata(created=created, run_id=run_id),
        "type": "memory_vault_topic",
        "entity": entity,
        "title": title,
        "tags": list(tags) if tags else [],
        "token_count": len(body) // 4,
    }
    if extra_meta:
        meta.update(extra_meta)
    text = _frontmatter_dump(meta) + "\n\n" + body.strip() + "\n"
    _write_text(path, text, root=root, source=f"memory_vault_topic:{entity}", run_id=run_id)
    return path


def write_global_digest(
    root: Path,
    *,
    day: Optional[datetime] = None,
    title: str = "Daily digest",
    body: str,
    sources: Optional[Iterable[str]] = None,
) -> Path:
    when = day or _now_utc()
    run_id = uuid.uuid4().hex[:12]
    dirpath = root / "global"
    dirpath.mkdir(parents=True, exist_ok=True)
    digest = _body_hash(body, extra=f"{title}:{when.isoformat()}")
    path = _unique_path(
        dirpath,
        f"{when.strftime('%Y%m%d-%H%M%S-%f')}-{slugify(title)}-{digest}.md",
    )
    created = _iso_z(when)
    meta = {
        **_base_metadata(created=created, run_id=run_id),
        "type": "memory_vault_global_digest",
        "title": title,
        "sources": list(sources) if sources else [],
        "token_count": len(body) // 4,
    }
    text = _frontmatter_dump(meta) + "\n\n" + body.strip() + "\n"
    _write_text(path, text, root=root, source="memory_vault_global_digest", run_id=run_id)
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
