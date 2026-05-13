"""
Skill registry API.

  GET  /api/skills                      — list every discovered skill manifest
  GET  /api/skills/{slug}               — single skill manifest
  POST /api/skills/validate             — validate an arbitrary manifest dict
  GET  /api/skills/third-party-registry — Zero-curated index of external skills
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any

from app.services.skill_manifest import (
    SkillManifest,
    discover_skills,
    load_from_dir,
    validate,
)

router = APIRouter()


# Default roots Zero scans for skills. The same roots feed the existing
# Discord / loop / character-content systems.
_SKILL_ROOTS = [
    Path(__file__).resolve().parents[3] / "skills",
    Path(__file__).resolve().parents[3] / ".claude" / "skills",
]
_THIRD_PARTY_REGISTRY = (
    Path(__file__).resolve().parents[3] / "skills" / "third-party-skills.json"
)


@router.get("/")
async def list_skills():
    items = []
    for manifest, validation in discover_skills(_SKILL_ROOTS):
        items.append(
            {
                **manifest.to_json(),
                "warnings": validation.warnings,
            }
        )
    return {"skills": items, "count": len(items)}


@router.get("/{slug}")
async def get_skill(slug: str):
    for root in _SKILL_ROOTS:
        skill_dir = root / slug
        if skill_dir.exists() and skill_dir.is_dir():
            manifest, validation = load_from_dir(skill_dir)
            if manifest is None:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "errors": validation.errors,
                        "warnings": validation.warnings,
                    },
                )
            return {**manifest.to_json(), "warnings": validation.warnings}
    raise HTTPException(status_code=404, detail=f"skill '{slug}' not found")


class ValidateRequest(BaseModel):
    manifest: dict[str, Any]


@router.post("/validate")
async def validate_manifest(req: ValidateRequest):
    result = validate(req.manifest)
    return {
        "ok": result.ok,
        "errors": result.errors,
        "warnings": result.warnings,
    }


@router.get("/third-party-registry")
async def third_party_registry():
    """List external skills the user can install. Mirrors openhuman's
    ``third-party-skills.json`` pattern."""
    if not _THIRD_PARTY_REGISTRY.exists():
        return {"entries": [], "registry_path": str(_THIRD_PARTY_REGISTRY)}
    try:
        data = json.loads(_THIRD_PARTY_REGISTRY.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"registry parse failed: {e}")
    if not isinstance(data, list):
        raise HTTPException(status_code=500, detail="registry must be a JSON array")
    return {"entries": data, "registry_path": str(_THIRD_PARTY_REGISTRY)}
