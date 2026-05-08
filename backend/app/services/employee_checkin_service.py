"""
Employee Check-in Service — Phase 036 (24/7 Employee).

Aggregates per-subsystem "employee report" payloads into a single EmployeeCheckin
row. The goal is one place to answer: "what has Zero accomplished?" for the
dashboard and skill.

Subsystems graded:
  - ops                (from daily_report_service.generate_daily_report)
  - carousels          (from daily_report_service.generate_carousel_employee_report)
  - research           (direct DB query — lowest research_depth_score, ready counts)
  - reference_videos   (direct DB query — ingest throughput, stuck rows, learnings applied)
  - audit              (direct DB query — carousels re-audited, issues found, fixes applied)

All grades are capped 0-100. Regressions are surfaced to the caller via the
skill layer (`/zero-employee-checkin`), which investigates and fixes directly.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Awaitable, Dict, List, Optional

import structlog
from sqlalchemy import and_, func as sa_func, select

from app.db.models import (
    CharacterCarouselModel,
    CharacterModel,
    CharacterReferenceVideoModel,
    EmployeeCheckinModel,
)
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)


_REGRESSION_THRESHOLD = 5.0  # points, used by the skill layer


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Subsystem report builders (fresh DB queries, no cross-service heavy lifting)
# ---------------------------------------------------------------------------


async def _research_report(window_hours: int = 24) -> Dict[str, Any]:
    since = _now() - timedelta(hours=window_hours)
    async with get_session() as session:
        total_chars = (await session.execute(
            select(sa_func.count(CharacterModel.id))
        )).scalar() or 0
        completed = (await session.execute(
            select(sa_func.count(CharacterModel.id))
            .where(CharacterModel.research_status == "completed")
        )).scalar() or 0
        # research_depth_score is stored on a 0-100 scale; "low depth" = below 50.
        low_depth = (await session.execute(
            select(sa_func.count(CharacterModel.id))
            .where(CharacterModel.research_depth_score < 50.0)
        )).scalar() or 0
        recently_researched = (await session.execute(
            select(sa_func.count(CharacterModel.id))
            .where(CharacterModel.last_researched >= since)
        )).scalar() or 0
        avg_depth = (await session.execute(
            select(sa_func.avg(CharacterModel.research_depth_score))
        )).scalar() or 0.0

    # Grade: blends completion rate (50%), avg depth (30%), low-depth pressure (20%).
    # avg_depth_score is stored on a 0-100 scale; normalize to 0-1 before blending.
    completion_rate = (completed / total_chars) if total_chars else 0.0
    low_pressure = max(0.0, 1.0 - (low_depth / total_chars)) if total_chars else 0.0
    avg_depth_norm = min(1.0, max(0.0, float(avg_depth) / 100.0))
    raw = 100.0 * (completion_rate * 0.5 + avg_depth_norm * 0.3 + low_pressure * 0.2)
    grade = round(min(100.0, max(0.0, raw)), 1)
    return {
        "subsystem": "research",
        "grade": grade,
        "metrics": {
            "total_characters": int(total_chars),
            "researched_completed": int(completed),
            "low_depth_backlog": int(low_depth),
            "recently_researched_24h": int(recently_researched),
            "avg_depth_score": round(float(avg_depth), 3),
        },
        "issues": (
            [f"{low_depth} characters have depth score < 50/100"] if low_depth > 5 else []
        ),
        "wins": (
            [f"{recently_researched} characters researched in last {window_hours}h"]
            if recently_researched else []
        ),
    }


async def _reference_video_report(window_hours: int = 24) -> Dict[str, Any]:
    since = _now() - timedelta(hours=window_hours)
    async with get_session() as session:
        status_rows = await session.execute(
            select(
                CharacterReferenceVideoModel.status,
                sa_func.count(CharacterReferenceVideoModel.id),
            ).group_by(CharacterReferenceVideoModel.status)
        )
        status_counts = {r[0]: int(r[1]) for r in status_rows.all()}

        recent_ready = (await session.execute(
            select(sa_func.count(CharacterReferenceVideoModel.id))
            .where(
                CharacterReferenceVideoModel.status == "ready",
                CharacterReferenceVideoModel.analyzed_at >= since,
            )
        )).scalar() or 0

        applied_learnings = (await session.execute(
            select(sa_func.count(CharacterReferenceVideoModel.id))
            .where(CharacterReferenceVideoModel.learnings_applied_at.is_not(None))
        )).scalar() or 0

        total = sum(status_counts.values())
        failed = status_counts.get("failed", 0)
        stuck = status_counts.get("downloading", 0) + status_counts.get("transcribing", 0) + status_counts.get("analyzing", 0)

    # Grade: penalize high failure rate + stuck pipeline
    failure_rate = (failed / total) if total else 0.0
    throughput = min(1.0, recent_ready / 5.0)  # 5 videos/window = "good"
    raw = (100.0 * max(0.0, 1.0 - failure_rate) * 0.5) + (throughput * 50.0)
    grade = round(min(100.0, max(0.0, raw)), 1)
    issues: List[str] = []
    if failed > 3:
        issues.append(f"{failed} reference videos failed ingest (likely path or yt-dlp issues)")
    if stuck > 5:
        issues.append(f"{stuck} reference videos stuck in intermediate states")
    wins: List[str] = []
    if recent_ready:
        wins.append(f"{recent_ready} reference videos analyzed in last {window_hours}h")
    return {
        "subsystem": "reference_videos",
        "grade": grade,
        "metrics": {
            "total": total,
            "by_status": status_counts,
            "analyzed_in_window": int(recent_ready),
            "learnings_applied_lifetime": int(applied_learnings),
        },
        "issues": issues,
        "wins": wins,
    }


async def _audit_report(window_hours: int = 24) -> Dict[str, Any]:
    since = _now() - timedelta(hours=window_hours)
    async with get_session() as session:
        audited_recent = (await session.execute(
            select(sa_func.count(CharacterCarouselModel.id))
            .where(CharacterCarouselModel.last_audited_at >= since)
        )).scalar() or 0
        never_audited = (await session.execute(
            select(sa_func.count(CharacterCarouselModel.id))
            .where(
                CharacterCarouselModel.last_audited_at.is_(None),
                CharacterCarouselModel.status.in_(
                    ["approved", "pending_review", "published", "ai_reviewed"]
                ),
            )
        )).scalar() or 0

    grade = 50.0
    if audited_recent:
        grade = min(100.0, 50.0 + (audited_recent * 2.5))
    if never_audited > 100:
        grade = max(grade - 20.0, 10.0)

    issues = ([f"{never_audited} eligible carousels have never been audited"]
              if never_audited > 50 else [])
    wins = ([f"{audited_recent} carousels re-audited in last {window_hours}h"]
            if audited_recent else [])
    return {
        "subsystem": "audit",
        "grade": round(grade, 1),
        "metrics": {
            "audited_in_window": int(audited_recent),
            "never_audited_eligible": int(never_audited),
        },
        "issues": issues,
        "wins": wins,
    }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class EmployeeCheckinService:
    async def run_checkin(self, window_hours: int = 24) -> Dict[str, Any]:
        """Generate all subsystem reports and persist the aggregate check-in.

        Must return fast (<3s) since it's called from the dashboard button.
        Each subsystem runs under its own timeout; a slow/failed subsystem
        degrades gracefully instead of stalling the whole check-in.

        Regressions are detected and included in the response's
        ``regressions`` list; remediation is driven by the
        ``/zero-employee-checkin`` skill, not by this service.
        """
        timings: Dict[str, int] = {}

        async def _timed(name: str, coro: Awaitable[Any], *, timeout: float, fallback: Any) -> Any:
            start = time.perf_counter()
            try:
                result = await asyncio.wait_for(coro, timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning("employee_checkin_timeout", subsystem=name, timeout=timeout)
                result = fallback
            except Exception as e:
                logger.warning("employee_checkin_subsystem_failed", subsystem=name, error=str(e))
                result = fallback
            finally:
                timings[name] = int((time.perf_counter() - start) * 1000)
            return result

        # Ops — fast path only (no LLM/health sections)
        from app.services.daily_report_service import get_daily_report_service
        svc = get_daily_report_service()
        ops_summary: Dict[str, Any] = await _timed(
            "ops",
            svc.compute_ops_grade_fast(window_hours=window_hours),
            timeout=2.0,
            fallback={"grade": 0, "job_summary": {}, "failed_jobs": []},
        )
        ops_grade = float(ops_summary.get("grade", 0) or 0)

        # Carousel — use the existing employee report, but cap it
        carousel_report: Dict[str, Any] = await _timed(
            "carousels",
            svc.generate_carousel_employee_report(window_hours=window_hours),
            timeout=3.0,
            fallback={"carousels": {}, "issues": ["carousel report timed out"], "wins": []},
        )
        carousel_grade: float = 50.0
        s2 = (carousel_report.get("carousels", {}) or {}).get("stage2_avg_score")
        if s2 is not None:
            carousel_grade = round(float(s2) * 10.0, 1)

        research, refvideo, audit = await asyncio.gather(
            _timed("research", _research_report(window_hours=window_hours), timeout=2.0,
                   fallback={"subsystem": "research", "grade": 50.0, "metrics": {},
                             "issues": ["research report timed out"], "wins": []}),
            _timed("reference_videos", _reference_video_report(window_hours=window_hours), timeout=2.0,
                   fallback={"subsystem": "reference_videos", "grade": 50.0, "metrics": {},
                             "issues": ["reference video report timed out"], "wins": []}),
            _timed("audit", _audit_report(window_hours=window_hours), timeout=2.0,
                   fallback={"subsystem": "audit", "grade": 50.0, "metrics": {},
                             "issues": ["audit report timed out"], "wins": []}),
        )

        carousel_sub = {
            "subsystem": "carousels",
            "grade": carousel_grade,
            "metrics": carousel_report.get("carousels", {}) if carousel_report else {},
            "issues": carousel_report.get("issues", []) if carousel_report else [],
            "wins": carousel_report.get("wins", []) if carousel_report else [],
        }
        ops_sub = {
            "subsystem": "ops",
            "grade": float(ops_grade),
            "metrics": ops_summary.get("job_summary") or {},
            "issues": [f"job failed: {n}" for n in (ops_summary.get("failed_jobs") or [])],
            "wins": [],
        }

        subsystems = [ops_sub, carousel_sub, research, refvideo, audit]
        overall = round(sum(s["grade"] for s in subsystems) / len(subsystems), 1)

        accomplishments = {
            "research_recent_24h": research["metrics"].get("recently_researched_24h", 0),
            "reference_videos_analyzed": refvideo["metrics"].get("analyzed_in_window", 0),
            "carousels_audited": audit["metrics"].get("audited_in_window", 0),
            "carousels_created": (carousel_report.get("carousels", {}) or {}).get("generated", 0),
        }
        issues = [i for s in subsystems for i in s.get("issues", [])]
        wins = [w for s in subsystems for w in s.get("wins", [])]

        checkin_id = f"chk-{uuid.uuid4().hex[:16]}"
        regressions = await self._detect_regressions(subsystems)

        full_report = {
            "subsystems": subsystems,
            "carousel_report": carousel_report,
            "window_hours": window_hours,
            "regressions": regressions,
        }
        subsystem_grades = {s["subsystem"]: s["grade"] for s in subsystems}

        created_at = _now()
        async with get_session() as session:
            row = EmployeeCheckinModel(
                id=checkin_id,
                created_at=created_at,
                ops_grade=ops_grade,
                overall_grade=overall,
                subsystem_grades=subsystem_grades,
                accomplishments=accomplishments,
                issues=issues,
                wins=wins,
                legion_task_ids=[],
                full_report=full_report,
            )
            session.add(row)
            await session.flush()

        logger.info(
            "employee_checkin_done",
            id=checkin_id,
            overall=overall,
            ops=ops_grade,
            regressions=len(regressions),
        )
        logger.info("employee_checkin_timings", **timings, total_ms=sum(timings.values()))
        # Mirror the shape of `/checkin/latest` so the frontend can treat the
        # mutation response identically to a fetched snapshot.
        return {
            "id": checkin_id,
            "created_at": created_at.isoformat(),
            "ops_grade": ops_grade,
            "overall_grade": overall,
            "subsystem_grades": subsystem_grades,
            "accomplishments": accomplishments,
            "issues": issues,
            "wins": wins,
            "legion_task_ids": [],
            "full_report": full_report,
            # Convenience fields — also exposed flat for existing callers
            "subsystems": subsystems,
            "regressions": regressions,
        }

    async def _detect_regressions(self, subsystems: List[dict]) -> List[Dict[str, Any]]:
        """Compare each subsystem's grade to the 7-day rolling average and
        return a list of regression descriptors for the skill layer to act on."""
        out: List[Dict[str, Any]] = []
        since = _now() - timedelta(days=7)
        async with get_session() as session:
            q = (
                select(EmployeeCheckinModel)
                .where(EmployeeCheckinModel.created_at >= since)
                .order_by(EmployeeCheckinModel.created_at.desc())
                .limit(20)
            )
            history = (await session.execute(q)).scalars().all()

        if not history:
            return out

        sub_avgs: Dict[str, float] = {}
        for s in subsystems:
            key = s["subsystem"]
            values = [
                float(row.subsystem_grades.get(key, 0) or 0)
                for row in history
                if row.subsystem_grades and key in row.subsystem_grades
            ]
            if values:
                sub_avgs[key] = sum(values) / len(values)

        for s in subsystems:
            baseline = sub_avgs.get(s["subsystem"])
            if baseline is None:
                continue
            drop = baseline - float(s["grade"])
            if drop <= _REGRESSION_THRESHOLD:
                continue
            out.append({
                "subsystem": s["subsystem"],
                "current": float(s["grade"]),
                "baseline_7d": round(baseline, 1),
                "drop": round(drop, 1),
                "severity": "high" if drop > 15 else "medium",
                "issues": s.get("issues", []),
            })
        return out


@lru_cache()
def get_employee_checkin_service() -> EmployeeCheckinService:
    return EmployeeCheckinService()
