"""F-37 — one-screen view of meeting-steward health.

Aggregates everything the user needs to know about Zero's meeting
subsystem: companion policy + active meeting, pending approvals,
recent notifications, host_agent + recording capability, transcript
backlog, last janitor run, follow-up ledger size, open meeting-spawned
tasks, privacy / consent policy snapshots.

Pure aggregator — no side effects. Frontend polls this every 15 s.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.get("/")
async def meeting_steward_status() -> dict[str, Any]:
    out: dict[str, Any] = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "ok": True,
        "issues": [],
    }

    # Companion policy + active meeting
    try:
        from app.services.reachy_companion_service import (
            get_reachy_companion_service,
        )

        policy = get_reachy_companion_service().get_policy()
        out["companion"] = {
            "mode": policy.mode,
            "transcribe_only": policy.transcribe_only,
            "meeting_active": policy.meeting_active,
            "meeting_active_id": policy.meeting_active_id,
            "last_wake_at": policy.last_wake_at.isoformat() if policy.last_wake_at else None,
            "wake_response_window_s": policy.wake_response_window_s,
        }
    except Exception as exc:
        out["companion"] = {"error": str(exc)}
        out["issues"].append({"id": "companion", "detail": str(exc)})

    # host_agent /health + Enhancement-09 /state snapshot
    try:
        import httpx

        host_url = os.getenv("ZERO_HOST_AGENT_URL", "http://host.docker.internal:18796").rstrip("/")
        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(f"{host_url}/health")
            data = r.json() if r.status_code < 400 else {}
            host_agent_block: dict[str, Any] = {
                "ok": bool(data.get("ok")),
                "wake_mode": data.get("wake", {}).get("mode"),
                "recordings_dir": data.get("recordings_dir"),
                "url": host_url,
            }
            # Pull persisted state if /state is exposed (Enhancement-09).
            try:
                s = await c.get(f"{host_url}/state")
                if s.status_code < 400:
                    sdata = s.json() or {}
                    host_agent_block["state"] = sdata.get("state") or {}
                    active = (host_agent_block["state"] or {}).get("active_recording")
                    if active:
                        out["issues"].append({
                            "id": "host_agent_active_recording",
                            "detail": (
                                f"host_agent still thinks meeting "
                                f"{active.get('meeting_id')} is recording — may be a "
                                "crashed capture from a prior boot."
                            ),
                        })
            except Exception:
                pass
            out["host_agent"] = host_agent_block
            if not data.get("ok"):
                out["issues"].append({"id": "host_agent", "detail": f"status={r.status_code}"})
    except Exception as exc:
        out["host_agent"] = {"ok": False, "error": str(exc)}
        out["issues"].append({"id": "host_agent", "detail": str(exc)})

    # Pending approvals
    try:
        from sqlalchemy import select, func
        from app.infrastructure.database import get_session
        from app.db.models import AgentApprovalModel  # type: ignore

        async with get_session() as db:
            pending = (
                await db.execute(
                    select(func.count())
                    .select_from(AgentApprovalModel)
                    .where(AgentApprovalModel.status == "pending")
                )
            ).scalar_one()
        out["approvals"] = {"pending": int(pending or 0)}
    except Exception as exc:
        out["approvals"] = {"error": str(exc)}

    # Notification bus -- recent + counts of meeting-related event types.
    # As of Enhancement-11, the bus is DB-backed so this survives restarts.
    try:
        from app.services.notification_bus import get_notification_bus

        events = await get_notification_bus().recent(limit=25)
        by_type: dict[str, int] = {}
        for e in events:
            t = str(e.get("type") or "")
            by_type[t] = by_type.get(t, 0) + 1
        last_alarm = next(
            (e for e in reversed(events) if e.get("type") == "meeting.health.alarm"),
            None,
        )
        last_failure = next(
            (e for e in reversed(events) if e.get("type") == "meeting.processing.failed"),
            None,
        )
        out["notifications"] = {
            "recent_count": len(events),
            "by_type": by_type,
            "last_alarm": last_alarm,
            "last_processing_failure": last_failure,
            "tail": events[-5:],  # most recent 5, surfaced in the steward UI
        }
        if last_failure:
            out["issues"].append({
                "id": "meeting_processing_failure",
                "detail": f"recent pipeline failure for meeting {last_failure.get('meeting_id')}",
            })
    except Exception as exc:
        out["notifications"] = {"error": str(exc)}

    # Transcript backlog
    try:
        from sqlalchemy import select, func
        from app.infrastructure.database import get_session
        from app.db.models import MeetingModel  # type: ignore

        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        async with get_session() as db:
            stuck = (
                await db.execute(
                    select(func.count())
                    .select_from(MeetingModel)
                    .where(MeetingModel.status == "processing")
                    .where(MeetingModel.updated_at < one_hour_ago)
                )
            ).scalar_one()
            total_processing = (
                await db.execute(
                    select(func.count())
                    .select_from(MeetingModel)
                    .where(MeetingModel.status == "processing")
                )
            ).scalar_one()
        out["transcript_backlog"] = {
            "stuck_over_1h": int(stuck or 0),
            "total_processing": int(total_processing or 0),
        }
        if stuck:
            out["issues"].append({
                "id": "transcript_backlog",
                "detail": f"{stuck} meeting(s) stuck > 1h",
            })
    except Exception as exc:
        out["transcript_backlog"] = {"error": str(exc)}

    # Janitor last run
    try:
        from app.infrastructure.config import get_workspace_path

        log_path = get_workspace_path("meetings") / "janitor_log.json"
        if log_path.exists():
            history = json.loads(log_path.read_text(encoding="utf-8"))
            if history:
                out["janitor"] = history[-1]
            else:
                out["janitor"] = {"never_run": True}
        else:
            out["janitor"] = {"never_run": True}
    except Exception as exc:
        out["janitor"] = {"error": str(exc)}

    # Follow-up ledger + open meeting actions
    try:
        from app.infrastructure.config import get_workspace_path

        ledger_path = get_workspace_path("meetings") / "followup_ledger.json"
        if ledger_path.exists():
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            out["followup_ledger"] = {
                "total": len(ledger),
                "last": (
                    sorted(ledger.values(), key=lambda v: v.get("ran_at", ""))[-1]
                    if ledger else None
                ),
            }
        else:
            out["followup_ledger"] = {"total": 0}
    except Exception as exc:
        out["followup_ledger"] = {"error": str(exc)}

    try:
        from app.services.meeting_open_actions_service import (
            get_meeting_open_actions_service,
        )

        open_actions = await get_meeting_open_actions_service().list_open(limit=10)
        out["open_meeting_actions"] = {
            "count": len(open_actions),
            "items": open_actions,
        }
    except Exception as exc:
        out["open_meeting_actions"] = {"error": str(exc)}

    # Concurrency queue + private meetings
    try:
        from app.services.meeting_concurrency_service import (
            get_meeting_concurrency_service,
        )

        out["concurrency_queue"] = {
            "queued": get_meeting_concurrency_service().list_queued(),
        }
    except Exception as exc:
        out["concurrency_queue"] = {"error": str(exc)}

    try:
        from app.services.meeting_privacy_service import (
            get_meeting_privacy_service,
        )

        out["privacy"] = {
            "private_meetings": get_meeting_privacy_service().list_private(),
        }
    except Exception as exc:
        out["privacy"] = {"error": str(exc)}

    # Compute overall health badge
    if out["issues"]:
        out["ok"] = False
    return out


@router.get("/weekly-analytics")
async def weekly_analytics() -> dict[str, Any]:
    """F-73 — week-over-week meeting analytics for the dashboard tile.

    Returns counts + minutes + top attendees + action-item completion
    rate for this week and last week. Reads from MeetingModel +
    meeting_followup ledger + TaskModel tagged meeting_followup. No new
    DB tables; everything is computed on demand.
    """
    from sqlalchemy import select, func
    from app.infrastructure.database import get_session
    from app.db.models import MeetingModel, TaskModel  # type: ignore

    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=7)
    prev_week_start = now - timedelta(days=14)

    async def _week_stats(start: datetime, end: datetime) -> dict[str, Any]:
        async with get_session() as db:
            count = (
                await db.execute(
                    select(func.count())
                    .select_from(MeetingModel)
                    .where(MeetingModel.start_time >= start)
                    .where(MeetingModel.start_time < end)
                )
            ).scalar_one()
            rows = (
                await db.execute(
                    select(
                        MeetingModel.duration_seconds,
                        MeetingModel.participants,
                    )
                    .where(MeetingModel.start_time >= start)
                    .where(MeetingModel.start_time < end)
                )
            ).all()
        total_seconds = 0
        attendee_tally: dict[str, int] = {}
        for dur, parts in rows:
            if dur:
                total_seconds += int(dur)
            for p in (parts or []):
                s = str(p or "").strip()
                if not s:
                    continue
                if "<" in s and ">" in s:
                    s = s[s.find("<") + 1 : s.find(">")].strip()
                attendee_tally[s] = attendee_tally.get(s, 0) + 1
        top_attendees = sorted(
            attendee_tally.items(), key=lambda kv: kv[1], reverse=True
        )[:5]
        return {
            "count": int(count or 0),
            "minutes": int(total_seconds // 60),
            "top_attendees": [{"name": n, "meetings": k} for n, k in top_attendees],
        }

    this_week = await _week_stats(week_start, now)
    prev_week = await _week_stats(prev_week_start, week_start)

    # Action-item completion rate this week.
    completion: dict[str, Any] = {}
    try:
        from sqlalchemy import or_

        async with get_session() as db:
            total = (
                await db.execute(
                    select(func.count())
                    .select_from(TaskModel)
                    .where(
                        or_(
                            TaskModel.source_reference.like("meeting:%"),
                            TaskModel.tags.contains(["meeting_followup"]),
                        )
                    )
                    .where(TaskModel.created_at >= week_start)
                )
            ).scalar_one()
            done = (
                await db.execute(
                    select(func.count())
                    .select_from(TaskModel)
                    .where(
                        or_(
                            TaskModel.source_reference.like("meeting:%"),
                            TaskModel.tags.contains(["meeting_followup"]),
                        )
                    )
                    .where(TaskModel.created_at >= week_start)
                    .where(TaskModel.status.in_(["DONE", "completed"]))
                )
            ).scalar_one()
    except Exception as exc:
        total = 0
        done = 0
        completion["error"] = str(exc)
    completion.update({
        "total": int(total or 0),
        "done": int(done or 0),
        "ratio": round((done / total) if total else 0.0, 3),
    })

    return {
        "checked_at": now.isoformat(),
        "this_week": this_week,
        "previous_week": prev_week,
        "delta_count": this_week["count"] - prev_week["count"],
        "delta_minutes": this_week["minutes"] - prev_week["minutes"],
        "action_item_completion": completion,
    }


@router.get("/janitor/last")
async def janitor_last() -> dict[str, Any]:
    """Last meeting_recordings_janitor run summary (F-42 helper)."""
    try:
        from app.infrastructure.config import get_workspace_path

        log_path = get_workspace_path("meetings") / "janitor_log.json"
        if not log_path.exists():
            return {"never_run": True}
        history = json.loads(log_path.read_text(encoding="utf-8"))
        return {"runs": history[-5:], "total_runs": len(history)}
    except Exception as exc:
        return {"error": str(exc)}
