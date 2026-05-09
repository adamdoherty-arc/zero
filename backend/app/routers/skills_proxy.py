"""Skills proxy — Zero UI -> Legion's skills registry.

The canonical skill registry lives in Legion. The Zero UI is the management
surface. To avoid a second CORS dance and to centralize auth, the Zero
backend exposes a thin proxy that forwards to Legion.

Endpoints mirror Legion 1:1 under `/api/skills` and `/api/teams`.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.infrastructure.auth import require_auth
from app.services.legion_client import get_legion_client

router = APIRouter(
    prefix="/api",
    tags=["Skills (proxy)"],
    dependencies=[Depends(require_auth)],
)


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------


@router.get("/skills")
async def list_skills(
    owner_project: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    team_id: Optional[int] = Query(default=None),
    deprecated: Optional[bool] = Query(default=None),
    search: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"limit": limit}
    if owner_project:
        params["owner_project"] = owner_project
    if category:
        params["category"] = category
    if team_id is not None:
        params["team_id"] = team_id
    if deprecated is not None:
        params["deprecated"] = deprecated
    if search:
        params["search"] = search
    client = get_legion_client()
    try:
        return await client._get("/skills", params=params)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"legion unavailable: {exc}")


@router.get("/skills/{name}")
async def get_skill(name: str) -> Dict[str, Any]:
    client = get_legion_client()
    try:
        result = await client._get(f"/skills/{name}")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"legion unavailable: {exc}")
    if not isinstance(result, dict) or result.get("error"):
        raise HTTPException(404, f"skill '{name}' not found in Legion registry")
    return result


class SkillPatchProxy(BaseModel):
    cron: Optional[str] = None
    judge_tier: Optional[str] = Field(default=None, pattern="^(local|none)$")
    daily_token_budget: Optional[int] = Field(default=None, ge=0)
    wallclock_budget_s: Optional[int] = Field(default=None, ge=10)
    auto_promote: Optional[bool] = None
    enabled: Optional[bool] = None
    team_id: Optional[int] = None


@router.patch("/skills/{name}")
async def patch_skill(name: str, req: SkillPatchProxy) -> Dict[str, Any]:
    client = get_legion_client()
    body = req.model_dump(exclude_unset=True)
    try:
        result = await client._patch(f"/skills/{name}", json=body)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"legion unavailable: {exc}")

    # Side-effect: propagate cron/enabled/budget changes to Zero's loops table
    # so the local scheduler reflects the UI edit immediately.
    if any(k in body for k in ("cron", "enabled", "daily_token_budget", "wallclock_budget_s", "auto_promote", "judge_tier")):
        try:
            from app.services.loop_registry_service import get_loop_registry
            registry = get_loop_registry()
            existing_loop = await registry.get_loop_by_name(name)
            if existing_loop is not None:
                upsert_payload: Dict[str, Any] = {
                    "name": name,
                    "owner_project": result.get("owner_project") or existing_loop["owner_project"],
                    "runner_kind": existing_loop["runner_kind"],
                    "runner_target": existing_loop["runner_target"],
                    "cron": result.get("cron") or existing_loop["cron"],
                    "enabled": result.get("enabled", existing_loop["enabled"]),
                    "judge_tier": result.get("judge_tier") or existing_loop["judge_tier"],
                    "auto_promote_enabled": result.get("auto_promote", existing_loop.get("auto_promote_enabled", True)),
                    "daily_token_budget": result.get("daily_token_budget", existing_loop["daily_token_budget"]),
                    "wall_clock_budget_s": result.get("wallclock_budget_s", existing_loop["wall_clock_budget_s"]),
                    "skill_name": name,
                    "description": result.get("description"),
                }
                await registry.upsert_loop(upsert_payload)
        except Exception as exc:  # noqa: BLE001
            # Don't fail the patch; the next sync cycle will heal eventually.
            pass

    return result


@router.post("/skills/sync")
async def sync_skills(body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    client = get_legion_client()
    try:
        return await client._post("/skills/sync", json=body or {})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"legion unavailable: {exc}")


@router.get("/skills/{name}/runs")
async def list_skill_runs(name: str, limit: int = Query(default=50, ge=1, le=500)) -> List[Dict[str, Any]]:
    client = get_legion_client()
    try:
        return await client._get(f"/skills/{name}/runs", params={"limit": limit})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"legion unavailable: {exc}")


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------


@router.get("/teams")
async def list_teams() -> List[Dict[str, Any]]:
    client = get_legion_client()
    try:
        return await client._get("/teams")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"legion unavailable: {exc}")


class TeamCreateProxy(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    display_name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    run_strategy: str = Field(default="parallel", pattern="^(parallel|sequential)$")
    composite_weights: Dict[str, float] = Field(default_factory=dict)


@router.post("/teams")
async def create_team(req: TeamCreateProxy) -> Dict[str, Any]:
    client = get_legion_client()
    try:
        return await client._post("/teams", json=req.model_dump())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"legion unavailable: {exc}")


class TeamPatchProxy(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    run_strategy: Optional[str] = Field(default=None, pattern="^(parallel|sequential)$")
    composite_weights: Optional[Dict[str, float]] = None


@router.get("/teams/{team_id}")
async def get_team(team_id: int) -> Dict[str, Any]:
    client = get_legion_client()
    try:
        result = await client._get(f"/teams/{team_id}")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"legion unavailable: {exc}")
    if not isinstance(result, dict) or result.get("error"):
        raise HTTPException(404, f"team {team_id} not found in Legion registry")
    return result


@router.patch("/teams/{team_id}")
async def patch_team(team_id: int, req: TeamPatchProxy) -> Dict[str, Any]:
    client = get_legion_client()
    try:
        return await client._patch(f"/teams/{team_id}", json=req.model_dump(exclude_unset=True))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"legion unavailable: {exc}")


class TeamMembersProxy(BaseModel):
    skill_ids: List[int] = Field(default_factory=list)


@router.put("/teams/{team_id}/members")
async def set_team_members(team_id: int, req: TeamMembersProxy) -> Dict[str, Any]:
    client = get_legion_client()
    try:
        # _request supports any method via session call
        url = f"{client.config.base_url}{client.config.api_prefix}/teams/{team_id}/members"
        async with httpx.AsyncClient(timeout=httpx.Timeout(20)) as c:
            resp = await c.put(url, json=req.model_dump())
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"legion unavailable: {exc}")


class TeamRunProxy(BaseModel):
    trigger_source: str = Field(default="manual", pattern="^(manual|cron|webhook)$")
    trigger_args: Dict[str, Any] = Field(default_factory=dict)


@router.post("/teams/{team_id}/run")
async def trigger_team_run(team_id: int, req: TeamRunProxy) -> Dict[str, Any]:
    client = get_legion_client()
    try:
        return await client._post(f"/teams/{team_id}/run", json=req.model_dump())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"legion unavailable: {exc}")


@router.get("/teams/{team_id}/runs")
async def list_team_runs(team_id: int, limit: int = Query(default=20, ge=1, le=200)) -> List[Dict[str, Any]]:
    client = get_legion_client()
    try:
        return await client._get(f"/teams/{team_id}/runs", params={"limit": limit})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"legion unavailable: {exc}")
