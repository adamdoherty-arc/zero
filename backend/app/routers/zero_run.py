"""Zero Supervisor surface — mirrors Legion's /api/legion/run/* and ADA's
/api/ada/run/*, adapted for Zero's stack.

Endpoints:
  POST /api/zero/run/start                — begin a supervisor run
  POST /api/zero/run/event                — record a gate event
  GET  /api/zero/run/active-plan          — current Zero plan (vault MANDATE.md)
  GET  /api/zero/run/{run_id}             — fetch a run + its events
  GET  /api/zero/sprints/next-priority    — proxies Legion :8005 (project_id=7)
  GET  /api/zero/stack-facts              — live infra truth
  POST /api/zero/critic/review            — queue a clean-context critic
  GET  /api/zero/critic/reviews/{id}      — poll a critic review
  GET  /api/zero/critic/reviews           — list critic reviews

Sprint state lives in Legion at host.docker.internal:8005, project_id=7.
The /next-priority endpoint just re-shapes Legion's response. These tables
capture supervisor gate events + critic reviews; nothing else.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Query
from sqlalchemy import select, text as sa_text

from app.infrastructure.database import get_session
from app.models.zero_run import ZeroCriticReviewDB, ZeroRunDB, ZeroRunEventDB

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/zero", tags=["Zero Supervisor"])


# ============================================================================
# RUN + EVENT
# ============================================================================

@router.post("/run/start")
async def run_start(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Begin a supervisor run. Body: {goal, focus?, supervisor_version?,
    robot_state?, dnd?}. Returns: {run_id, started_at}."""
    goal = body.get("goal")
    if not goal:
        raise HTTPException(status_code=400, detail="goal required")
    run_id = str(uuid.uuid4())

    async with get_session() as session:
        row = ZeroRunDB(
            run_id=run_id,
            goal=goal,
            focus=body.get("focus"),
            status="running",
            robot_state=body.get("robot_state"),
            dnd=body.get("dnd"),
            supervisor_version=body.get("supervisor_version", "zero-supervisor-v1"),
        )
        session.add(row)
        await session.flush()
        evt = ZeroRunEventDB(
            run_id=run_id,
            phase="0",
            event="zero.run.started",
            payload={"goal": goal, "focus": body.get("focus")},
            robot_state=body.get("robot_state"),
            dnd=body.get("dnd"),
        )
        session.add(evt)
        started_at = row.started_at

    return {
        "run_id": run_id,
        "started_at": started_at.isoformat() if started_at else None,
        "status": "running",
    }


@router.post("/run/event")
async def run_event(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Record a supervisor gate event. Body envelope:
    {run_id, phase, event, payload?, metrics?, links?, robot_state?, dnd?,
     partition?, approval_record_id?, vault_audit_id?, salience?,
     delegation_target?, legion_sprint_id?}.

    On zero.run.closed / zero.run.closed_early — updates the run row.
    """
    run_id = body.get("run_id")
    event = body.get("event")
    if not run_id or not event:
        raise HTTPException(status_code=400, detail="run_id + event required")

    async with get_session() as session:
        evt = ZeroRunEventDB(
            run_id=run_id,
            phase=body.get("phase"),
            event=event,
            payload=body.get("payload"),
            metrics=body.get("metrics"),
            links=body.get("links"),
            robot_state=body.get("robot_state"),
            dnd=body.get("dnd"),
            partition=body.get("partition"),
            approval_record_id=body.get("approval_record_id"),
            vault_audit_id=body.get("vault_audit_id"),
            salience=body.get("salience"),
            delegation_target=body.get("delegation_target"),
            legion_sprint_id=body.get("legion_sprint_id"),
        )
        session.add(evt)
        await session.flush()
        event_id = evt.id
        ts = evt.ts

        run_status = "running"
        if event in ("zero.run.closed", "zero.run.closed_early"):
            run = (await session.execute(
                select(ZeroRunDB).where(ZeroRunDB.run_id == run_id)
            )).scalar_one_or_none()
            if run:
                run.status = "completed"
                run.ended_at = datetime.now(timezone.utc)
                payload = body.get("payload") or {}
                if isinstance(payload, dict):
                    run.summary = payload.get("summary")
                run.metrics = body.get("metrics")
                run_status = "completed"
        elif event == "zero.preflight.blocked" and (body.get("payload") or {}).get("escalate"):
            run = (await session.execute(
                select(ZeroRunDB).where(ZeroRunDB.run_id == run_id)
            )).scalar_one_or_none()
            if run:
                run.status = "blocked"
                run_status = "blocked"

    return {
        "event_id": event_id,
        "ts": ts.isoformat() if ts else None,
        "run_status": run_status,
    }


@router.get("/run/active-plan")
async def active_plan() -> dict[str, Any]:
    """Current Zero plan markdown. Tries MANDATE.md, then the vault
    Constitution, then the operator's active plan slot."""
    candidates = [
        Path("/c/code/zero/MANDATE.md"),
        Path("/app/MANDATE.md"),
        Path("/c/code/vault/ObsidianZero/00_Meta/CLAUDE.md"),
        Path("/vault/00_Meta/CLAUDE.md"),
        Path("/c/code/zero/.claude/MEMORY.md"),
    ]
    for c in candidates:
        try:
            if c.exists():
                txt = c.read_text(encoding="utf-8")
                return {
                    "source": "markdown_file",
                    "markdown_path": str(c),
                    "markdown_source": txt,
                    "markdown_bytes": len(txt.encode("utf-8")),
                }
        except Exception:  # noqa: BLE001
            continue
    return {"source": "none", "note": "No plan file reachable."}


@router.get("/run/{run_id}")
async def run_detail(run_id: str) -> dict[str, Any]:
    async with get_session() as session:
        run = (await session.execute(
            select(ZeroRunDB).where(ZeroRunDB.run_id == run_id)
        )).scalar_one_or_none()
        if not run:
            raise HTTPException(status_code=404, detail=f"run {run_id} not found")
        events = (await session.execute(
            select(ZeroRunEventDB)
            .where(ZeroRunEventDB.run_id == run_id)
            .order_by(ZeroRunEventDB.ts)
        )).scalars().all()
        return {
            "run_id": run.run_id,
            "goal": run.goal,
            "focus": run.focus,
            "status": run.status,
            "robot_state": run.robot_state,
            "dnd": run.dnd,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "ended_at": run.ended_at.isoformat() if run.ended_at else None,
            "summary": run.summary,
            "metrics": run.metrics,
            "supervisor_version": run.supervisor_version,
            "events": [
                {
                    "id": e.id,
                    "ts": e.ts.isoformat() if e.ts else None,
                    "phase": e.phase,
                    "event": e.event,
                    "payload": e.payload,
                    "metrics": e.metrics,
                    "links": e.links,
                    "robot_state": e.robot_state,
                    "dnd": e.dnd,
                    "partition": e.partition,
                    "approval_record_id": e.approval_record_id,
                    "vault_audit_id": e.vault_audit_id,
                    "salience": e.salience,
                    "delegation_target": e.delegation_target,
                    "legion_sprint_id": e.legion_sprint_id,
                }
                for e in events
            ],
            "event_count": len(events),
        }


# ============================================================================
# SPRINTS — Zero sprints live in Legion (project_id=7)
# ============================================================================

@router.get("/sprints/next-priority")
async def sprints_next_priority(
    limit: int = Query(default=5, ge=1, le=50),
    source_prefix: str | None = Query(default=None),
) -> dict[str, Any]:
    """Top-priority PLANNED Zero sprints, proxied from Legion :8005.
    Zero is project_id=7 in Legion (corrected from 8 on 2026-05-17)."""
    base = os.getenv("LEGION_API_URL", "http://host.docker.internal:8005").rstrip("/")
    project_id = int(os.getenv("ZERO_LEGION_PROJECT_ID", "7"))
    params: dict[str, Any] = {"project_id": project_id, "limit": limit}
    if source_prefix:
        params["source_prefix"] = source_prefix
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{base}/api/legion/sprints/next-priority", params=params)
            if r.status_code != 200:
                return {
                    "source": "legion_proxy",
                    "legion_status": r.status_code,
                    "error": r.text[:200],
                    "sprints": [],
                }
            data = r.json()
            data["source"] = "legion_proxy"
            data["legion_url"] = f"{base}/api/legion/sprints/next-priority"
            return data
    except Exception as e:  # noqa: BLE001
        return {
            "source": "legion_proxy",
            "error": f"unreachable: {e}",
            "sprints": [],
        }


# ============================================================================
# STACK FACTS — live infra truth
# ============================================================================

@router.get("/stack-facts")
async def stack_facts() -> dict[str, Any]:
    """Live infrastructure truth: Bifrost reachability, Reachy daemon state,
    host_agent state, vault indexer heartbeat, Langfuse reachability, MCP
    presence (cyanheads, legion-mcp, ada-mcp), alembic head."""
    bifrost_url = os.getenv("BIFROST_GATEWAY_URL", "http://shared-bifrost:8080").rstrip("/")
    bifrost_status = "unknown"
    bifrost_error: str | None = None
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{bifrost_url}/v1/models")
            bifrost_status = "reachable" if r.status_code in (200, 401) else f"http_{r.status_code}"
    except Exception as e:  # noqa: BLE001
        bifrost_status = "unreachable"
        bifrost_error = str(e)[:200]

    reachy = await _probe("http://host.docker.internal:8000/api/daemon/status", "reachy_daemon")
    host_agent = await _probe(
        os.getenv("ZERO_HOST_AGENT_URL", "http://host.docker.internal:18796") + "/health",
        "host_agent",
    )
    langfuse_url = os.getenv("LANGFUSE_HOST") or "http://zero-langfuse-web:3000"
    langfuse = await _probe(f"{langfuse_url}/api/public/health", "langfuse")

    # Alembic head + open approval count + vault indexer heartbeat
    alembic_head = None
    approvals_open = -1
    voice_active = -1
    async with get_session() as session:
        try:
            row = (await session.execute(sa_text("SELECT version_num FROM alembic_version"))).first()
            alembic_head = row[0] if row else None
        except Exception:  # noqa: BLE001
            alembic_head = None
        try:
            r = (await session.execute(sa_text(
                "SELECT COUNT(*) FROM approval_requests WHERE status IN ('pending','queued')"
            ))).scalar()
            approvals_open = int(r or 0)
        except Exception:  # noqa: BLE001
            approvals_open = -1

    return {
        "model": {
            "local": os.getenv("ZERO_VLLM_CHAT_MODEL", "vllm-local/Qwen3-32B-AWQ"),
            "embed": os.getenv("ZERO_VLLM_EMBED_MODEL", "Qwen/Qwen3-Embedding-0.6B"),
            "gateway": bifrost_url,
        },
        "ports": {
            "backend": 18792,
            "frontend": 5173,
            "frontend_dev": 5174,
            "postgres_host": 5434,
            "postgres_container": 5432,
            "reachy_daemon": 8000,
            "host_agent": 18796,
            "langfuse_host": 3010,
            "bifrost": 4445,
            "vllm_chat": 18800,
            "vllm_embed": 8001,
        },
        "network": {
            "bifrost_url": bifrost_url,
            "bifrost_status": bifrost_status,
            "bifrost_error": bifrost_error,
        },
        "reachy": reachy,
        "host_agent": host_agent,
        "langfuse": langfuse,
        "approvals": {"open": approvals_open},
        "voice": {
            "note": "Voice sessions tracked in Langfuse — see /api/zero/run/{id} → events for voice.session_started",
            "active_count": voice_active,
        },
        "mcp": _mcp_presence(),
        "vault": {
            "constitution": "/c/code/vault/ObsidianZero/00_Meta/CLAUDE.md",
            "writer": "app.services.vault_writer_service",
            "indexer": "app.services.vault_indexer_service",
            "cyanheads_route": "MCP cyanheads-obsidian (configured in .mcp.json)",
        },
        "delegation_targets": {
            "legion": os.getenv("LEGION_API_URL", "http://host.docker.internal:8005"),
            "ada": os.getenv("ADA_API_URL", "http://host.docker.internal:8003"),
            "claude_sonnet_for_long_context": ">200K tokens",
            "qwen3_chat_for_local_privacy": "sensitive personal reasoning",
        },
        "schema": {"alembic_head": alembic_head},
        "rules": {
            "claude_md": "/c/code/zero/CLAUDE.md",
            "mandate_md": "/c/code/zero/MANDATE.md",
            "rules_dir": "/c/code/zero/.claude/rules/",
            "scorecard": "/c/code/zero/.claude/memory/quality/MASTER_SCORECARD.md",
        },
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


# ============================================================================
# STAGE-2 READINESS
# ============================================================================

@router.get("/stage2/readiness")
async def stage2_readiness() -> dict[str, Any]:
    """Verify all Stage-2 prerequisites: Obsidian Local REST API, cyanheads
    MCP presence, and OBSIDIAN_API_KEY env var. Returns a structured status
    object suitable for surfacing in the dashboard Setup card.

    Obsidian Local REST API plugin must be installed and running at
    https://127.0.0.1:27124 with a valid OBSIDIAN_API_KEY for Stage-2
    vault writes to work via cyanheads-obsidian MCP.
    """
    checks: dict[str, Any] = {}

    # 1. OBSIDIAN_API_KEY present
    api_key = os.getenv("OBSIDIAN_API_KEY", "")
    checks["obsidian_api_key_set"] = bool(api_key)

    # 2. Obsidian Local REST API reachable (https, self-signed cert)
    obsidian_base = os.getenv("OBSIDIAN_BASE_URL", "https://127.0.0.1:27124")
    obsidian_status = "unreachable"
    obsidian_error: str | None = None
    try:
        async with httpx.AsyncClient(timeout=3.0, verify=False) as client:  # noqa: S501
            r = await client.get(
                obsidian_base.rstrip("/") + "/",
                headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            )
            obsidian_status = "reachable" if r.status_code in (200, 204, 401) else f"http_{r.status_code}"
    except Exception as e:  # noqa: BLE001
        obsidian_error = str(e)[:200]

    checks["obsidian_rest_api"] = {
        "url": obsidian_base,
        "status": obsidian_status,
        "error": obsidian_error,
    }

    # 3. cyanheads MCP presence (from _mcp_presence helper)
    mcp = _mcp_presence()
    checks["cyanheads_obsidian_mcp"] = mcp.get("cyanheads_obsidian", False)

    # Overall readiness
    ready = (
        checks["obsidian_api_key_set"]
        and obsidian_status == "reachable"
        and checks["cyanheads_obsidian_mcp"]
    )
    checks["ready"] = ready
    if not ready:
        missing = []
        if not checks["obsidian_api_key_set"]:
            missing.append("OBSIDIAN_API_KEY env var not set")
        if obsidian_status != "reachable":
            missing.append(
                f"Obsidian Local REST API unreachable at {obsidian_base} "
                "(install the 'Local REST API' community plugin in Obsidian and enable it)"
            )
        if not checks["cyanheads_obsidian_mcp"]:
            missing.append(
                "cyanheads-obsidian MCP server not connected "
                "(add it to .mcp.json and restart Claude Code)"
            )
        checks["setup_steps"] = missing
        checks["docs"] = "docs/stage2-mcp-setup.md"

    checks["as_of"] = datetime.now(timezone.utc).isoformat()
    return checks


# ============================================================================
# CRITIC
# ============================================================================

_CRITIC_PROMPT_TEMPLATE = """You are a code reviewer. You have not seen any prior context.

REVIEW the diff below against the ACCEPTANCE CRITERIA. Be unsparing. Do NOT
summarize the work — judge the artifacts directly. This is Zero, a
chief-of-staff assistant + Reachy voice + Company OS surface. Auto-REJECT
on: any direct vault write outside _agent/ that isn't routed through
cyanheads_obsidian MCP, any path introducing `partition: work`, any code
re-adding realtime auto-promote on FloatingVoiceButton, any external write
without an approvals_id, any financial-action code (must route to Ada).

---ACCEPTANCE CRITERIA (from sprint description)---
{ac}
---END ACCEPTANCE CRITERIA---

---DIFF (files changed)---
{diff}
---END DIFF---

Answer in <critique> tags. Score each question 0 (failed) or 1 (passed).

(1) Does each AC have a verifying command + observable PASS evidence in the diff?
(2) Are there silent skips, TODO stubs, pass/... bodies?
(3) Were tests written FOR the new code, or only re-run? Robot-off smoke covered if applicable?
(4) Any plan items in the AC that were NOT executed?
(5) Anything that violates the vault constitution / approval ladder / voice billing?

End with EXACTLY one of:
VERDICT: ACCEPT
VERDICT: REJECT

If REJECT, list the 1-3 specific issues to fix before re-review.
Keep your response under 600 words.
"""


def _extract_ac_from_description(description: str) -> str:
    if not description:
        return "(no description on sprint)"
    m = re.search(
        r"^ACCEPTANCE[^:\n]*:\s*\n(.+?)(?:\n[A-Z][A-Z_]+:|\Z)",
        description, re.DOTALL | re.MULTILINE,
    )
    if m:
        return m.group(1).strip()
    return description[:2000]


def _diff_for_files(files_changed: list[str], base: str = "HEAD~1") -> str:
    for repo in ("/c/code/zero", "/app"):
        if os.path.isdir(repo):
            cmd = ["git", "-C", repo, "diff", base, "--"] + (files_changed or [])
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                if result.returncode == 0:
                    return result.stdout[:12000] or "(no diff)"
                return f"(git diff failed: {result.stderr[:200]})"
            except Exception as e:  # noqa: BLE001
                return f"(diff capture error: {e})"
    return "(repo not mounted)"


async def _run_critic_background(
    review_id: int,
    files_changed: list[str],
    base_ref: str,
    ac: str,
    prompt: str,
) -> None:
    from app.infrastructure.bifrost_client import get_bifrost_client

    t0 = time.time()
    critique_text = ""
    model_used = "error"
    try:
        client = get_bifrost_client()
        model = os.getenv("ZERO_VLLM_CHAT_MODEL", "vllm-local/Qwen3-32B-AWQ")
        critique_text = await client.complete(
            model=model,
            messages=[
                {"role": "system", "content": (
                    "/no_think\nYou are a strict code reviewer. Never see prior context. "
                    "Only judge artifacts. Always end with VERDICT: ACCEPT or VERDICT: REJECT."
                )},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=2000,
        )
        model_used = model
    except Exception as e:  # noqa: BLE001
        critique_text = f"(critic LLM call failed: {e})"
        model_used = "error"
    latency_ms = int((time.time() - t0) * 1000)

    verdict = "ERROR"
    upper = critique_text.upper()
    if "VERDICT: ACCEPT" in upper:
        verdict = "ACCEPT"
    elif "VERDICT: REJECT" in upper:
        verdict = "REJECT"

    scores: dict[str, Any] = {}
    for (_, val), label in zip(
        re.compile(r"\((\d)\).*?(\b[01]\b)", re.DOTALL).findall(critique_text)[:5],
        ["ac", "stubs", "tests", "plan", "constitution_or_voice"],
    ):
        scores[label] = int(val)

    reject_reasons: list[str] = []
    if verdict == "REJECT":
        m = re.search(r"VERDICT:\s*REJECT\s*\n(.+?)\Z", critique_text, re.DOTALL | re.IGNORECASE)
        if m:
            reject_reasons = [
                line.strip().lstrip("-*0123456789. ").strip()
                for line in m.group(1).splitlines()
                if line.strip() and len(line.strip()) > 6
            ][:5]

    async with get_session() as session:
        row = (await session.execute(
            select(ZeroCriticReviewDB).where(ZeroCriticReviewDB.id == review_id)
        )).scalar_one_or_none()
        if row is None:
            return
        row.critique_text = critique_text[:8000]
        row.scores = scores or None
        row.verdict = verdict
        row.reject_reasons = reject_reasons or None
        row.model_used = model_used
        row.latency_ms = latency_ms


@router.post("/critic/review")
async def critic_review(
    background_tasks: BackgroundTasks,
    body: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Queue a clean-context critic. Body:
    {legion_sprint_id, files_changed?:[], run_id?, round?:1, base_ref?:'HEAD~1',
     sprint_description?, ac_override?}.

    sprint_description is read from the body so this endpoint doesn't depend
    on a live Legion call. If omitted, ac_override takes over."""
    sprint_id = body.get("legion_sprint_id") or body.get("sprint_id")
    if not sprint_id:
        raise HTTPException(status_code=400, detail="legion_sprint_id required")
    files_changed = body.get("files_changed") or []
    run_id = body.get("run_id")
    round_n = int(body.get("round", 1))
    base_ref = body.get("base_ref", "HEAD~1")
    description = body.get("sprint_description") or ""

    ac = body.get("ac_override") or _extract_ac_from_description(description)
    diff_text = _diff_for_files(files_changed, base=base_ref)
    prompt = _CRITIC_PROMPT_TEMPLATE.format(ac=ac, diff=diff_text)

    async with get_session() as session:
        row = ZeroCriticReviewDB(
            run_id=run_id,
            legion_sprint_id=int(sprint_id),
            round=round_n,
            files_reviewed=files_changed,
            ac_extracted=ac[:4000],
            critic_prompt=prompt[:8000],
            verdict=None,
        )
        session.add(row)
        await session.flush()
        review_id = row.id

    background_tasks.add_task(
        _run_critic_background, review_id, files_changed, base_ref, ac, prompt
    )
    return {
        "review_id": review_id,
        "legion_sprint_id": sprint_id,
        "round": round_n,
        "status": "queued",
        "poll_url": f"/api/zero/critic/reviews/{review_id}",
        "expected_latency_seconds": "60-180 (Bifrost → Qwen3)",
    }


@router.get("/critic/reviews/{review_id}")
async def critic_review_detail(review_id: int) -> dict[str, Any]:
    async with get_session() as session:
        row = (await session.execute(
            select(ZeroCriticReviewDB).where(ZeroCriticReviewDB.id == review_id)
        )).scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail=f"review {review_id} not found")
        return {
            "id": row.id,
            "run_id": row.run_id,
            "legion_sprint_id": row.legion_sprint_id,
            "round": row.round,
            "verdict": row.verdict,
            "scores": row.scores,
            "reject_reasons": row.reject_reasons,
            "critique_text": row.critique_text,
            "model_used": row.model_used,
            "latency_ms": row.latency_ms,
            "tokens_in": row.tokens_in,
            "tokens_out": row.tokens_out,
            "files_reviewed": row.files_reviewed,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "status": "completed" if row.verdict is not None else "queued",
        }


@router.get("/critic/reviews")
async def critic_review_list(
    legion_sprint_id: int | None = Query(default=None),
    run_id: str | None = Query(default=None),
    verdict: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
) -> dict[str, Any]:
    async with get_session() as session:
        stmt = select(ZeroCriticReviewDB).order_by(ZeroCriticReviewDB.id.desc()).limit(limit)
        if legion_sprint_id is not None:
            stmt = stmt.where(ZeroCriticReviewDB.legion_sprint_id == legion_sprint_id)
        if run_id is not None:
            stmt = stmt.where(ZeroCriticReviewDB.run_id == run_id)
        if verdict is not None:
            stmt = stmt.where(ZeroCriticReviewDB.verdict == verdict)
        rows = (await session.execute(stmt)).scalars().all()

    return {
        "reviews": [
            {
                "id": r.id,
                "run_id": r.run_id,
                "legion_sprint_id": r.legion_sprint_id,
                "round": r.round,
                "verdict": r.verdict,
                "scores": r.scores,
                "reject_reasons": r.reject_reasons,
                "model_used": r.model_used,
                "latency_ms": r.latency_ms,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "count": len(rows),
    }


# ============================================================================
# Helpers
# ============================================================================

async def _probe(url: str, label: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(url)
            return {
                "url": url,
                "status": "reachable" if r.status_code < 500 else f"http_{r.status_code}",
                "http": r.status_code,
            }
    except Exception as e:  # noqa: BLE001
        return {"url": url, "status": "unreachable", "error": str(e)[:120]}


def _mcp_presence() -> dict[str, Any]:
    """Best-effort: confirm the operator's .mcp.json declares the three
    MCP clients the supervisor depends on (legion-mcp, ada-mcp,
    cyanheads-obsidian)."""
    out: dict[str, Any] = {"legion_mcp": False, "ada_mcp": False, "cyanheads_obsidian": False}
    for p in (Path("/c/code/zero/.mcp.json"), Path("/app/.mcp.json")):
        try:
            if p.exists():
                txt = p.read_text(encoding="utf-8")
                if "legion-mcp" in txt:
                    out["legion_mcp"] = True
                if "ada-mcp" in txt:
                    out["ada_mcp"] = True
                if "cyanheads-obsidian" in txt:
                    out["cyanheads_obsidian"] = True
                out["mcp_json_path"] = str(p)
                break
        except Exception:  # noqa: BLE001
            continue
    return out
