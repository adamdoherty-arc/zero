"""
Skill manifest spec — extended from Zero's existing ``_meta.json`` to match
the openhuman skill manifest pattern: declare auth requirements, platforms,
triggers, and tool surface so a skill is both discoverable AND sandboxable.

A skill lives at ``skills/<slug>/`` (or any registered root) with:

    SKILL.md         — human-readable docs / system prompt
    skill.json       — extended manifest (this module's schema)
    _meta.json       — legacy slim metadata (still honored; auto-migrated)

This module parses, validates, and migrates legacy meta files into the
extended manifest shape without breaking anything currently shipped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import structlog

logger = structlog.get_logger(__name__)


# Auth scopes a skill can request. The companion service's ``action_allowed``
# check enforces these at call time.
KNOWN_AUTH_SCOPES = {
    "fs_read",          # read user files
    "fs_write",         # write user files
    "net_outbound",     # arbitrary HTTPS
    "shell",            # spawn shell processes
    "browser",          # headless browser control
    "memory_read",      # read Memory Tree
    "memory_write",     # write Memory Tree
    "calendar",         # Google Calendar
    "gmail",            # Gmail tools
    "github",           # GitHub repos
    "linear",           # Linear issues
    "slack",            # Slack workspace
    "notion",           # Notion pages
    "tts",              # text-to-speech output
    "motion",           # Reachy physical motion
}

KNOWN_PLATFORMS = {"darwin", "linux", "windows", "any"}
KNOWN_TRIGGER_KINDS = {"manual", "schedule", "event", "voice", "trigger_rule"}


@dataclass
class SkillManifest:
    """Validated skill manifest."""

    slug: str
    name: str
    version: str
    description: str = ""
    author: str = ""
    license: str = "unknown"
    auth: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=lambda: ["any"])
    triggers: list[dict] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    entry: Optional[str] = None  # path to executable/script (optional)
    sandbox: dict = field(default_factory=lambda: {"timeout_s": 30, "memory_mb": 256})
    homepage: Optional[str] = None
    repository: Optional[str] = None

    def to_json(self) -> dict:
        return {
            "slug": self.slug,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "license": self.license,
            "auth": list(self.auth),
            "platforms": list(self.platforms),
            "triggers": list(self.triggers),
            "tools": list(self.tools),
            "entry": self.entry,
            "sandbox": dict(self.sandbox),
            "homepage": self.homepage,
            "repository": self.repository,
        }


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate(raw: dict) -> ValidationResult:
    """Validate a raw manifest dict. Returns errors + warnings."""
    errors: list[str] = []
    warnings: list[str] = []

    # Required string fields
    for field_name in ("slug", "name", "version"):
        value = raw.get(field_name)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"field '{field_name}' is required and must be a non-empty string")

    slug = raw.get("slug", "")
    if slug and not all(c.isalnum() or c in "-_" for c in slug):
        errors.append(f"slug '{slug}' contains illegal characters; use [a-zA-Z0-9_-]")

    # Auth scopes must be known
    auth = raw.get("auth", []) or []
    if not isinstance(auth, list):
        errors.append("field 'auth' must be a list of scope strings")
    else:
        for scope in auth:
            if scope not in KNOWN_AUTH_SCOPES:
                warnings.append(f"unknown auth scope '{scope}' — may be ignored by sandbox")

    # Platforms
    platforms = raw.get("platforms", ["any"]) or ["any"]
    if not isinstance(platforms, list):
        errors.append("field 'platforms' must be a list of platform strings")
    else:
        for p in platforms:
            if p not in KNOWN_PLATFORMS:
                warnings.append(f"unknown platform '{p}'")

    # Triggers
    triggers = raw.get("triggers", []) or []
    if not isinstance(triggers, list):
        errors.append("field 'triggers' must be a list of trigger objects")
    else:
        for i, t in enumerate(triggers):
            if not isinstance(t, dict):
                errors.append(f"triggers[{i}] must be an object")
                continue
            kind = t.get("kind")
            if kind not in KNOWN_TRIGGER_KINDS:
                warnings.append(
                    f"triggers[{i}].kind='{kind}' is not in {sorted(KNOWN_TRIGGER_KINDS)}"
                )

    # Sandbox bounds
    sandbox = raw.get("sandbox") or {}
    if isinstance(sandbox, dict):
        timeout = sandbox.get("timeout_s", 30)
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            errors.append("sandbox.timeout_s must be a positive number")
        memory = sandbox.get("memory_mb", 256)
        if not isinstance(memory, int) or memory <= 0:
            errors.append("sandbox.memory_mb must be a positive integer")

    return ValidationResult(ok=not errors, errors=errors, warnings=warnings)


def parse(raw: dict, *, slug_override: Optional[str] = None) -> SkillManifest:
    """Parse a validated dict into a ``SkillManifest`` dataclass."""
    return SkillManifest(
        slug=slug_override or raw.get("slug", ""),
        name=raw.get("name", ""),
        version=raw.get("version", "0.0.0"),
        description=raw.get("description", ""),
        author=raw.get("author", ""),
        license=raw.get("license", "unknown"),
        auth=list(raw.get("auth", []) or []),
        platforms=list(raw.get("platforms", ["any"]) or ["any"]),
        triggers=list(raw.get("triggers", []) or []),
        tools=list(raw.get("tools", []) or []),
        entry=raw.get("entry"),
        sandbox=dict(raw.get("sandbox") or {"timeout_s": 30, "memory_mb": 256}),
        homepage=raw.get("homepage"),
        repository=raw.get("repository"),
    )


def migrate_legacy(meta: dict, *, slug: str, skill_md: Optional[str] = None) -> dict:
    """Promote a legacy ``_meta.json`` blob into the extended manifest shape.

    Zero's existing meta has: slug, version, publishedAt, ownerId. We pull
    the name + description from the first H1/paragraph of ``SKILL.md`` if
    available so existing skills get sensible defaults without manual work.
    """
    name = meta.get("name") or slug
    description = ""
    if skill_md:
        for line in skill_md.splitlines():
            line = line.strip()
            if line.startswith("# "):
                name = line[2:].strip()
                continue
            if line and not line.startswith("#"):
                description = line[:200]
                break

    return {
        "slug": meta.get("slug") or slug,
        "name": name,
        "version": meta.get("version", "1.0.0"),
        "description": description,
        "author": meta.get("ownerId") or "",
        "license": meta.get("license", "unknown"),
        "auth": [],
        "platforms": ["any"],
        "triggers": [],
        "tools": [],
        "sandbox": {"timeout_s": 30, "memory_mb": 256},
    }


def load_from_dir(skill_dir: Path) -> tuple[Optional[SkillManifest], ValidationResult]:
    """Load a skill manifest from disk. Returns (manifest, validation).

    Search order:
      1. ``skill.json`` — extended manifest (preferred)
      2. ``_meta.json`` — legacy; auto-migrated
    """
    slug = skill_dir.name
    extended = skill_dir / "skill.json"
    legacy = skill_dir / "_meta.json"
    raw: Optional[dict] = None

    if extended.exists():
        try:
            raw = json.loads(extended.read_text(encoding="utf-8"))
        except Exception as e:
            return None, ValidationResult(ok=False, errors=[f"skill.json parse failed: {e}"])
    elif legacy.exists():
        try:
            legacy_raw = json.loads(legacy.read_text(encoding="utf-8"))
        except Exception as e:
            return None, ValidationResult(ok=False, errors=[f"_meta.json parse failed: {e}"])
        skill_md_text = None
        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            try:
                skill_md_text = skill_md.read_text(encoding="utf-8")
            except Exception:
                pass
        raw = migrate_legacy(legacy_raw, slug=slug, skill_md=skill_md_text)
    else:
        return None, ValidationResult(
            ok=False,
            errors=[f"no skill.json or _meta.json in {skill_dir}"],
        )

    validation = validate(raw)
    if not validation.ok:
        return None, validation
    return parse(raw, slug_override=slug), validation


def discover_skills(roots: Iterable[Path]) -> list[tuple[SkillManifest, ValidationResult]]:
    """Walk every root for skill directories and load each one's manifest."""
    out: list[tuple[SkillManifest, ValidationResult]] = []
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            if child.name.startswith(".") or child.name.startswith("_"):
                continue
            manifest, validation = load_from_dir(child)
            if manifest is not None:
                out.append((manifest, validation))
            else:
                logger.warning(
                    "skill_manifest_invalid",
                    skill=child.name,
                    errors=validation.errors,
                )
    return out
