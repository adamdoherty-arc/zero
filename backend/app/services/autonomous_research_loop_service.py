"""
Autonomous Research Loop — 24/7 research driver.

Runs every N minutes (default 15). Each tick:
  1. Counts in-flight deep-research reports. Gates on max concurrency.
  2. Picks the best eligible topic from research_topics:
       - status=active
       - last_researched_at older than cooldown window (or NULL)
       - ordered by (never-researched first, then relevance_score desc)
  3. If no eligible topic, generates one from recent high-novelty findings,
     active project MOCs, or a built-in seed set so the loop never idles.
  4. Starts a deep-research run via DeepResearchService (fire-and-forget).
  5. After completion, a watcher spawns per report that writes the markdown
     into the Obsidian vault at 00_Meta/_agent/research/YYYY-MM-DD-slug.md
     and updates the topic's last_researched_at timestamp.

The goal is steady, bounded background research that produces vault artifacts
without user prompting. Budget and concurrency are the twin governors.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import and_, or_, select, update
from sqlalchemy.sql import func as sa_func

from app.db.models import (
    DeepResearchReportModel,
    ResearchFindingModel,
    ResearchTopicModel,
)
from app.infrastructure.config import get_settings
from app.infrastructure.database import get_session
from app.models.agent_company import DeepResearchRequest
from app.services.deep_research_service import get_deep_research_service
from app.services.vault_writer_service import get_vault_writer

logger = structlog.get_logger(__name__)


_DEFAULT_PERSPECTIVES = ["technical", "competitive", "business"]

# Last-resort topic seeds if the topic table is empty AND we have no findings yet.
# Intentionally Zero-adjacent: anything the system can learn and act on.
_BOOTSTRAP_TOPICS: list[dict[str, Any]] = [
    {
        "name": "LangGraph supervisor patterns 2026",
        "description": "Multi-agent supervisor vs swarm patterns, handoff via Command(goto=..., graph=PARENT).",
        "search_queries": [
            "LangGraph supervisor multi-agent 2026",
            "LangChain Command handoff graph parent",
            "LangGraph deep-agents patterns",
        ],
        "aspects": _DEFAULT_PERSPECTIVES,
    },
    {
        "name": "Obsidian MCP write-back 2026",
        "description": "cyanheads obsidian-mcp-server features + Local REST API patch-heading behavior.",
        "search_queries": [
            "cyanheads obsidian mcp server",
            "Obsidian Local REST API patch heading",
            "Obsidian MCP write-back agents 2026",
        ],
        "aspects": ["technical", "security"],
    },
    {
        "name": "Reachy Mini voice stack Parakeet Kokoro",
        "description": "Local voice loop: Silero VAD, Parakeet TDT, Kokoro 82M TTS, LiveKit Agents with MCP.",
        "search_queries": [
            "Reachy Mini conversation app fastrtc",
            "Parakeet TDT vs faster-whisper distil-large-v3",
            "LiveKit Agents MCP native support 2026",
            "Kokoro FastAPI TTS streaming",
        ],
        "aspects": ["technical", "latency"],
    },
    {
        "name": "pgvector partitioned retrieval hybrid BM25 dense",
        "description": "pgvector HNSW tuning, Reciprocal Rank Fusion with tsvector, partition routing.",
        "search_queries": [
            "pgvector HNSW m ef_construction tuning",
            "BM25 dense RRF Postgres tsvector",
            "Anthropic contextual retrieval chunking 2025",
        ],
        "aspects": ["technical"],
    },
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AutonomousResearchLoopService:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._research = get_deep_research_service()
        self._vault = get_vault_writer()
        self._spent_usd_today: float = 0.0
        self._spent_date: Optional[str] = None

    # ------------------------------------------------------------------
    # Budget bookkeeping (rough — real cost tracking lives in llm_router)
    # ------------------------------------------------------------------

    def _reset_budget_if_new_day(self) -> None:
        today = _now().strftime("%Y-%m-%d")
        if self._spent_date != today:
            self._spent_date = today
            self._spent_usd_today = 0.0

    def _can_spend(self, estimate_usd: float) -> bool:
        self._reset_budget_if_new_day()
        return (self._spent_usd_today + estimate_usd) <= self._settings.autonomous_research_daily_budget_usd

    def _record_spend(self, amount_usd: float) -> None:
        self._reset_budget_if_new_day()
        self._spent_usd_today += amount_usd

    # ------------------------------------------------------------------
    # Concurrency gate
    # ------------------------------------------------------------------

    async def _in_flight_count(self) -> int:
        in_flight_statuses = ("pending", "outlining", "researching", "validating", "assembling")
        async with get_session() as session:
            result = await session.execute(
                select(sa_func.count(DeepResearchReportModel.id)).where(
                    DeepResearchReportModel.status.in_(in_flight_statuses)
                )
            )
            return int(result.scalar() or 0)

    # ------------------------------------------------------------------
    # Topic selection
    # ------------------------------------------------------------------

    async def _pick_eligible_topic(self) -> Optional[ResearchTopicModel]:
        cutoff = _now() - timedelta(hours=self._settings.autonomous_research_topic_cooldown_hours)
        async with get_session() as session:
            result = await session.execute(
                select(ResearchTopicModel)
                .where(
                    and_(
                        ResearchTopicModel.status == "active",
                        or_(
                            ResearchTopicModel.last_researched_at.is_(None),
                            ResearchTopicModel.last_researched_at < cutoff,
                        ),
                    )
                )
                .order_by(
                    ResearchTopicModel.last_researched_at.asc().nullsfirst(),
                    ResearchTopicModel.relevance_score.desc(),
                )
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def _generate_topic_from_findings(self) -> Optional[dict[str, Any]]:
        """Promote the highest-novelty recent finding into a new topic."""
        async with get_session() as session:
            result = await session.execute(
                select(ResearchFindingModel)
                .where(ResearchFindingModel.status != "archived")
                .order_by(
                    ResearchFindingModel.novelty_score.desc(),
                    ResearchFindingModel.composite_score.desc(),
                )
                .limit(1)
            )
            finding = result.scalar_one_or_none()
        if finding is None:
            return None
        name = finding.title[:120]
        return {
            "name": name,
            "description": f"Auto-generated from finding {finding.id}: {finding.llm_summary or finding.snippet[:200]}",
            "search_queries": [finding.title],
            "aspects": _DEFAULT_PERSPECTIVES,
            "source_finding_id": finding.id,
        }

    async def _ensure_bootstrap_topics(self) -> Optional[ResearchTopicModel]:
        """If no active topic exists, seed one from the bootstrap set."""
        async with get_session() as session:
            result = await session.execute(
                select(sa_func.count(ResearchTopicModel.id)).where(
                    ResearchTopicModel.status == "active"
                )
            )
            active_count = int(result.scalar() or 0)
            if active_count > 0:
                return None

        for seed in _BOOTSTRAP_TOPICS:
            topic_id = f"rt-{uuid.uuid4().hex[:10]}"
            async with get_session() as session:
                row = ResearchTopicModel(
                    id=topic_id,
                    name=seed["name"],
                    description=seed["description"],
                    search_queries=list(seed.get("search_queries", [])),
                    aspects=list(seed.get("aspects", _DEFAULT_PERSPECTIVES)),
                    status="active",
                    frequency="daily",
                    relevance_score=60.0,
                )
                session.add(row)
                await session.commit()
        logger.info("autonomous_research_bootstrap_seeded", count=len(_BOOTSTRAP_TOPICS))
        # return the first seeded topic for immediate use
        async with get_session() as session:
            result = await session.execute(
                select(ResearchTopicModel).where(ResearchTopicModel.status == "active").limit(1)
            )
            return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Dispatch + completion watcher
    # ------------------------------------------------------------------

    async def _dispatch(self, topic: ResearchTopicModel) -> Optional[str]:
        aspects = list(topic.aspects or []) or list(_DEFAULT_PERSPECTIVES)
        query = topic.name
        if topic.search_queries:
            query = f"{topic.name} — {topic.search_queries[0]}"
        req = DeepResearchRequest(query=query, perspectives=aspects)
        report = await self._research.start_research(req)
        async with get_session() as session:
            await session.execute(
                update(ResearchTopicModel)
                .where(ResearchTopicModel.id == topic.id)
                .values(last_researched_at=_now())
            )
            await session.commit()
        logger.info(
            "autonomous_research_dispatched",
            topic_id=topic.id,
            topic=topic.name,
            report_id=report.id,
        )
        asyncio.create_task(self._watch_and_write(report.id, topic.name))
        return report.id

    async def _watch_and_write(self, report_id: str, topic_name: str, *, timeout_seconds: int = 1800) -> None:
        """Poll the report until completed/failed, then write into the vault."""
        start = asyncio.get_event_loop().time()
        poll_seconds = 20
        last_status: Optional[str] = None
        while True:
            await asyncio.sleep(poll_seconds)
            now = asyncio.get_event_loop().time()
            if now - start > timeout_seconds:
                logger.warning(
                    "autonomous_research_watch_timeout",
                    report_id=report_id,
                    topic=topic_name,
                )
                return
            report = await self._research.get_report(report_id)
            if report is None:
                logger.warning("autonomous_research_report_missing", report_id=report_id)
                return
            if report.status != last_status:
                logger.info(
                    "autonomous_research_status",
                    report_id=report_id,
                    status=report.status,
                )
                last_status = report.status
            if report.status in ("completed", "failed"):
                break

        if report.status != "completed":
            logger.warning(
                "autonomous_research_report_failed",
                report_id=report_id,
                topic=topic_name,
            )
            return

        if not self._vault.available():
            logger.warning(
                "autonomous_research_vault_unavailable",
                vault=self._settings.vault_path,
                report_id=report_id,
            )
            return

        sources = []
        try:
            for s in (report.sources or [])[:40]:
                title = s.get("title") or s.get("url") or ""
                url = s.get("url") or ""
                if title and url:
                    sources.append(f"[{title}]({url})")
                elif url:
                    sources.append(url)
        except Exception:  # noqa: BLE001
            sources = []

        try:
            written = self._vault.write_research_report(
                topic=topic_name,
                markdown=report.report_markdown or "",
                executive_summary=report.executive_summary or "",
                sources=sources,
                report_id=report.id,
            )
            logger.info(
                "autonomous_research_vault_written",
                report_id=report.id,
                path=written["relative"],
                bytes=written["bytes"],
            )
        except Exception as e:  # noqa: BLE001
            logger.error(
                "autonomous_research_vault_write_failed",
                report_id=report.id,
                error=str(e),
            )

    # ------------------------------------------------------------------
    # Public tick entry point
    # ------------------------------------------------------------------

    async def _sweep_completed_reports_to_vault(self) -> int:
        """Export any completed deep-research reports that don't yet have a vault file.

        The in-process watcher can die if the container restarts mid-pipeline. This
        sweep is idempotent, runs at the top of every tick, and ensures every
        completed report lands in 00_Meta/_agent/research/ eventually.
        """
        if not self._vault.available():
            return 0

        since = _now() - timedelta(hours=48)
        async with get_session() as session:
            result = await session.execute(
                select(DeepResearchReportModel)
                .where(
                    and_(
                        DeepResearchReportModel.status == "completed",
                        DeepResearchReportModel.completed_at >= since,
                    )
                )
                .order_by(DeepResearchReportModel.completed_at.desc())
                .limit(20)
            )
            reports = list(result.scalars().all())

        vault_dir = (
            self._vault.vault_root / self._settings.vault_agent_research_subdir
        )
        written = 0
        for report in reports:
            today = report.completed_at.strftime("%Y-%m-%d") if report.completed_at else _now().strftime("%Y-%m-%d")
            slug = (report.query or "untitled").lower()
            # Match the slug rules used in vault_writer_service._slug
            import re as _re
            slug = _re.sub(r"[^a-z0-9]+", "-", slug).strip("-")[:60] or "untitled"
            target = vault_dir / f"{today}-{slug}.md"
            if target.exists():
                continue
            try:
                sources = []
                for s in (report.sources or [])[:40]:
                    title = s.get("title") or s.get("url") or ""
                    url = s.get("url") or ""
                    if title and url:
                        sources.append(f"[{title}]({url})")
                    elif url:
                        sources.append(url)
                self._vault.write_research_report(
                    topic=report.query,
                    markdown=report.report_markdown or "",
                    executive_summary=report.executive_summary or "",
                    sources=sources,
                    report_id=report.id,
                )
                written += 1
                logger.info("autonomous_research_vault_sweep_written", report_id=report.id)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "autonomous_research_vault_sweep_write_failed",
                    report_id=report.id,
                    error=str(e),
                )
        return written

    async def tick(self) -> dict[str, Any]:
        """One iteration of the loop. Safe to call from the scheduler."""
        if not self._settings.autonomous_research_enabled:
            return {"status": "disabled"}

        # Catch up: export any completed reports we missed (container restart etc.)
        swept = await self._sweep_completed_reports_to_vault()

        in_flight = await self._in_flight_count()
        if in_flight >= self._settings.autonomous_research_max_concurrent:
            logger.info("autonomous_research_gated_concurrency", in_flight=in_flight)
            return {"status": "gated", "reason": "concurrency", "in_flight": in_flight}

        if not self._can_spend(0.5):  # coarse estimate: $0.50 per run
            logger.info("autonomous_research_gated_budget", spent=self._spent_usd_today)
            return {"status": "gated", "reason": "budget", "spent_usd": self._spent_usd_today}

        topic = await self._pick_eligible_topic()
        if topic is None:
            # Try to auto-generate from findings first.
            gen = await self._generate_topic_from_findings()
            if gen is not None:
                topic_id = f"rt-{uuid.uuid4().hex[:10]}"
                async with get_session() as session:
                    row = ResearchTopicModel(
                        id=topic_id,
                        name=gen["name"],
                        description=gen["description"],
                        search_queries=list(gen.get("search_queries", [])),
                        aspects=list(gen.get("aspects", _DEFAULT_PERSPECTIVES)),
                        status="active",
                        frequency="daily",
                        relevance_score=55.0,
                    )
                    session.add(row)
                    await session.commit()
                    await session.refresh(row)
                topic = row
                logger.info("autonomous_research_generated_topic", topic=gen["name"])
            else:
                # Final fallback: bootstrap.
                topic = await self._ensure_bootstrap_topics()

        if topic is None:
            return {"status": "idle", "reason": "no_topic"}

        report_id = await self._dispatch(topic)
        self._record_spend(0.5)
        return {
            "status": "dispatched",
            "topic_id": topic.id,
            "topic": topic.name,
            "report_id": report_id,
            "in_flight_before": in_flight,
            "spent_usd_today": self._spent_usd_today,
            "vault_swept": swept,
        }

    async def status(self) -> dict[str, Any]:
        self._reset_budget_if_new_day()
        in_flight = await self._in_flight_count()
        async with get_session() as session:
            active_topics = int(
                (
                    await session.execute(
                        select(sa_func.count(ResearchTopicModel.id)).where(
                            ResearchTopicModel.status == "active"
                        )
                    )
                ).scalar()
                or 0
            )
            completed_today = int(
                (
                    await session.execute(
                        select(sa_func.count(DeepResearchReportModel.id)).where(
                            and_(
                                DeepResearchReportModel.status == "completed",
                                DeepResearchReportModel.completed_at
                                >= _now().replace(hour=0, minute=0, second=0, microsecond=0),
                            )
                        )
                    )
                ).scalar()
                or 0
            )
        return {
            "enabled": self._settings.autonomous_research_enabled,
            "interval_minutes": self._settings.autonomous_research_interval_minutes,
            "max_concurrent": self._settings.autonomous_research_max_concurrent,
            "cooldown_hours": self._settings.autonomous_research_topic_cooldown_hours,
            "daily_budget_usd": self._settings.autonomous_research_daily_budget_usd,
            "spent_usd_today": self._spent_usd_today,
            "in_flight": in_flight,
            "active_topics": active_topics,
            "completed_reports_today": completed_today,
            "vault_available": self._vault.available(),
            "vault_path": self._settings.vault_path,
        }


_singleton: Optional[AutonomousResearchLoopService] = None


def get_autonomous_research_loop() -> AutonomousResearchLoopService:
    global _singleton
    if _singleton is None:
        _singleton = AutonomousResearchLoopService()
    return _singleton
