"""Loops Router — read API + admin toggles for the cross-project loop framework.

Wires the registry into the public surface:
- GET    /api/loops                       list registry
- GET    /api/loops/{id}                  one loop
- GET    /api/loops/{id}/runs             run history
- GET    /api/loops/{id}/variants         variant pool
- POST   /api/loops                       upsert (admin)
- POST   /api/loops/{id}/enable           enable (admin)
- POST   /api/loops/{id}/disable          disable (admin)
- POST   /api/loops/{id}/trigger          manual run (admin)
- GET    /api/loops/queue                 OpenCode daemon polling endpoint
- POST   /api/loops/runs/{id}/complete    OpenCode daemon completion callback
- GET    /api/loops/health                health probe for the watchdog
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.infrastructure.auth import require_auth
from app.services.loop_registry_service import get_loop_registry
from app.services.loop_runner_service import get_loop_runner

health_router = APIRouter(
    prefix="/api/loops",
    tags=["Loops"],
)

router = APIRouter(
    prefix="/api/loops",
    tags=["Loops"],
    dependencies=[Depends(require_auth)],
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class LoopUpsertRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    owner_project: str = Field(..., pattern="^(zero|legion|ada|llmrouter|global)$")
    runner_kind: str = Field(..., pattern="^(claude_skill|opencode|http|prompt_variant)$")
    runner_target: str
    cron: str = Field(default="manual", max_length=80)
    enabled: bool = False
    sandbox_required: bool = False
    judge_tier: str = Field(default="local", pattern="^(local|none)$")
    auto_promote_enabled: bool = True
    daily_token_budget: int = Field(default=200_000, ge=0)
    daily_run_cap: int = Field(default=48, ge=1)
    wall_clock_budget_s: int = Field(default=600, ge=10)
    description: Optional[str] = None
    skill_name: Optional[str] = Field(default=None, max_length=150)


class RunCompleteRequest(BaseModel):
    status: str = Field(..., pattern="^(success|failure|timeout|budget_paused)$")
    judge_score: Optional[float] = Field(default=None, ge=0, le=100)
    judge_notes: Optional[str] = None
    vault_path: Optional[str] = None
    cost_tokens: Optional[int] = Field(default=None, ge=0)
    output: Optional[str] = None
    error: Optional[str] = None
    legion_run_id: Optional[int] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------


@health_router.get("/health")
async def loops_health():
    """Lightweight liveness probe for the health-watchdog NSSM service."""
    registry = get_loop_registry()
    try:
        loops = await registry.list_loops()
        return {
            "status": "ok",
            "total_loops": len(loops),
            "enabled_loops": sum(1 for l in loops if l["enabled"]),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"loops registry unavailable: {exc}")


@router.get("")
async def list_loops(
    owner_project: Optional[str] = Query(default=None, pattern="^(zero|legion|ada)$"),
    enabled_only: bool = Query(default=False),
):
    return await get_loop_registry().list_loops(
        owner_project=owner_project,
        enabled_only=enabled_only,
    )


@router.get("/queue")
async def loops_queue(
    runner: str = Query(..., pattern="^(opencode|claude_skill|http|prompt_variant)$"),
    max_concurrent: int = Query(default=1, ge=1, le=4),
):
    """Polled by the OpenCode loop daemon (P3) and any other external runner.

    Returns 0 or `max_concurrent` due loops matching the runner kind.
    P0: returns [] (registry has no enabled rows yet).
    """
    due = await get_loop_registry().next_due_loops(within_seconds=300, limit=max_concurrent * 2)
    matching = [l for l in due if l["runner_kind"] == runner][:max_concurrent]
    return {"runner": runner, "jobs": matching}


@router.get("/{loop_id}")
async def get_loop(loop_id: int):
    loop = await get_loop_registry().get_loop(loop_id)
    if not loop:
        raise HTTPException(404, f"loop {loop_id} not found")
    return loop


@router.get("/{loop_id}/runs")
async def list_runs(loop_id: int, limit: int = Query(default=50, ge=1, le=500)):
    return await get_loop_registry().list_runs(loop_id, limit=limit)


@router.get("/{loop_id}/variants")
async def list_variants(loop_id: int):
    return await get_loop_registry().list_variants(loop_id)


# ---------------------------------------------------------------------------
# Admin / mutation endpoints
# ---------------------------------------------------------------------------


@router.post("")
async def upsert_loop(req: LoopUpsertRequest):
    return await get_loop_registry().upsert_loop(req.model_dump())


@router.post("/{loop_id}/enable")
async def enable_loop(loop_id: int):
    loop = await get_loop_registry().set_enabled(loop_id, True)
    if not loop:
        raise HTTPException(404, f"loop {loop_id} not found")
    return loop


@router.post("/{loop_id}/disable")
async def disable_loop(loop_id: int):
    loop = await get_loop_registry().set_enabled(loop_id, False)
    if not loop:
        raise HTTPException(404, f"loop {loop_id} not found")
    return loop


@router.post("/{loop_id}/trigger")
async def trigger_loop(loop_id: int):
    """Manually run one loop (bypasses cron).

    Returns immediately with `{loop_id, run_id, status: "dispatched"}` while
    the actual work continues in a background task. Track progress via
    `GET /api/loops/runs/{run_id}`. The synchronous variant blocks for the
    full duration of the run (often minutes for claude_skill), which times
    out fan-out callers like Legion's team-trigger.
    """
    loop = await get_loop_registry().get_loop(loop_id)
    if not loop:
        raise HTTPException(404, f"loop {loop_id} not found")
    return await get_loop_runner().dispatch_background(loop)


@router.get("/runs/{run_id}")
async def get_run(run_id: int):
    """Lookup a single run by id — used by Legion's team_run_completer."""
    run = await get_loop_registry().get_run(run_id)
    if not run:
        raise HTTPException(404, f"run {run_id} not found")
    return run


@router.post("/judge/run")
async def run_judge(limit: int = Query(default=20, ge=1, le=200)):
    """Score recent successful runs that have a null judge_score.

    Usually triggered by the scheduler's `loop_judge_15min` job; this manual
    endpoint is for surfacing scores immediately (e.g., after a team-run).
    """
    from app.services.loop_judge_service import get_loop_judge
    judge = get_loop_judge()
    return await judge.score_recent_runs(limit=limit)


@router.post("/runs/{run_id}/complete")
async def complete_run(run_id: int, req: RunCompleteRequest):
    """Called by external runners (OpenCode daemon, http projects) to finalize a run."""
    result = await get_loop_registry().mark_run_completed(
        run_id,
        status=req.status,
        judge_score=req.judge_score,
        judge_notes=req.judge_notes,
        vault_path=req.vault_path,
        cost_tokens=req.cost_tokens,
        output=req.output,
        error=req.error,
        legion_run_id=req.legion_run_id,
        run_metadata=req.metadata or None,
    )
    if not result:
        raise HTTPException(404, f"run {run_id} not found")
    return result
