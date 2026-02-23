"""
Research Agent Service.
Autonomous web research, discovery scoring, knowledge accumulation, and self-improvement.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from functools import lru_cache
import structlog
import uuid

from sqlalchemy import select, update, delete, func as sql_func, or_

from app.infrastructure.database import get_session
from app.infrastructure.config import get_settings, get_workspace_path
from app.db.models import (
    ResearchTopicModel,
    ResearchFindingModel,
    ResearchCycleModel,
    ServiceConfigModel,
)
from app.models.research import (
    ResearchTopic, ResearchTopicCreate, ResearchTopicUpdate,
    ResearchTopicStatus, ResearchFinding, FindingStatus, FindingCategory,
    ResearchCycleResult, ResearchStats, FeedbackEntry,
)
from app.services.searxng_service import get_searxng_service

logger = structlog.get_logger()

# Zero project ID in Legion (from config)
ZERO_PROJECT_ID = get_settings().zero_legion_project_id

DEFAULT_TOPICS = [
    {
        "name": "AI Assistant Frameworks",
        "description": "Open source AI assistant frameworks, personal AI projects",
        "searchQueries": [
            "open source AI personal assistant 2026",
            "AI assistant framework github new",
            "personal AI agent open source project",
        ],
        "aspects": ["new projects", "architecture patterns", "unique features", "community adoption"],
        "categoryTags": ["ai", "assistant", "framework"],
    },
    {
        "name": "LangGraph & LangChain Ecosystem",
        "description": "New tools, patterns, and projects in the LangGraph/LangChain ecosystem",
        "searchQueries": [
            "LangGraph new features 2026",
            "LangChain multi-agent patterns",
            "LangGraph agent orchestration examples",
        ],
        "aspects": ["new releases", "best practices", "example projects", "migration guides"],
        "categoryTags": ["langgraph", "langchain", "agents"],
    },
    {
        "name": "AI Chat UIs",
        "description": "Chat UIs, AI assistant frontends, kanban + AI integrations",
        "searchQueries": [
            "AI chat UI open source 2026",
            "AI assistant frontend react",
            "kanban board AI integration",
        ],
        "aspects": ["UI libraries", "design patterns", "new projects", "feature ideas"],
        "categoryTags": ["ui", "frontend", "chat"],
    },
    {
        "name": "AI Skills & Plugins",
        "description": "AI agent skills, tool use patterns, MCP servers, plugin systems",
        "searchQueries": [
            "AI agent skills plugin system",
            "MCP server new tools 2026",
            "AI agent tool use patterns",
        ],
        "aspects": ["new tools", "plugin architectures", "MCP servers", "skill patterns"],
        "categoryTags": ["skills", "plugins", "mcp", "tools"],
    },
    {
        "name": "Self-Hosted AI Automation",
        "description": "Self-hosted AI automation, local LLM workflows, Ollama projects",
        "searchQueries": [
            "self-hosted AI automation 2026",
            "Ollama project ideas new",
            "local LLM workflow automation",
        ],
        "aspects": ["new projects", "automation patterns", "Ollama integrations", "self-hosted tools"],
        "categoryTags": ["self-hosted", "automation", "ollama"],
    },
]

DEFAULT_CONFIG = {
    "llm": {
        "model": None,  # Use LLM router default (was: qwen3:8b)
        "temperature": 0.3,
        "max_tokens": 2500,
        "timeout": 180,
    },
    "daily": {
        "max_topics_per_cycle": 5,
        "max_results_per_query": 10,
        "max_auto_tasks_per_cycle": 3,
        "high_value_threshold": 65,
    },
    "weekly": {
        "max_results_per_query": 15,
        "generate_trend_report": True,
        "extra_qualifiers": ["github trending", "hacker news", "reddit"],
    },
    "scoring_weights": {
        "relevance": 0.35,
        "novelty": 0.25,
        "actionability": 0.40,
    },
    "retention": {
        "max_findings": 2000,
        "max_cycles": 100,
        "max_feedback": 500,
    },
}

_SERVICE_CONFIG_KEY = "research"
_FEEDBACK_CONFIG_KEY = "research_feedback"


def _generate_id(prefix: str) -> str:
    """Generate a short unique ID with a prefix."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def get_research_path():
    return get_workspace_path("research")


def _topic_model_to_pydantic(row: ResearchTopicModel) -> ResearchTopic:
    """Convert a ResearchTopicModel ORM row to a ResearchTopic Pydantic model."""
    return ResearchTopic(
        id=row.id,
        name=row.name,
        description=row.description,
        search_queries=row.search_queries or [],
        aspects=row.aspects or [],
        category_tags=row.category_tags or [],
        status=row.status,
        frequency=row.frequency,
        last_researched_at=row.last_researched_at,
        findings_count=row.findings_count,
        relevance_score=row.relevance_score,
    )


def _finding_model_to_pydantic(row: ResearchFindingModel) -> ResearchFinding:
    """Convert a ResearchFindingModel ORM row to a ResearchFinding Pydantic model."""
    return ResearchFinding(
        id=row.id,
        topic_id=row.topic_id or "",
        title=row.title,
        url=row.url,
        snippet=row.snippet or "",
        source_engine=row.source_engine,
        category=row.category,
        status=row.status,
        relevance_score=row.relevance_score,
        novelty_score=row.novelty_score,
        actionability_score=row.actionability_score,
        composite_score=row.composite_score,
        llm_summary=row.llm_summary,
        tags=row.tags or [],
        suggested_task=row.suggested_task,
        linked_task_id=row.linked_task_id,
        discovered_at=row.discovered_at,
        reviewed_at=row.reviewed_at,
    )


def _cycle_model_to_pydantic(row: ResearchCycleModel) -> ResearchCycleResult:
    """Convert a ResearchCycleModel ORM row to a ResearchCycleResult Pydantic model."""
    return ResearchCycleResult(
        cycle_id=row.id,
        started_at=row.started_at,
        completed_at=row.completed_at,
        topics_researched=row.topics_researched,
        total_results=row.total_results,
        new_findings=row.new_findings,
        duplicate_filtered=row.duplicate_filtered,
        high_value_findings=row.high_value_findings,
        tasks_created=row.tasks_created,
        errors=row.errors or [],
    )


class ResearchService:
    """
    Autonomous research agent that discovers, scores, and tracks
    external developments relevant to Zero's improvement.
    """

    def __init__(self):
        self.settings = get_settings()

    # =========================================================================
    # CONFIGURATION
    # =========================================================================

    async def _get_config(self) -> Dict[str, Any]:
        async with get_session() as session:
            result = await session.execute(
                select(ServiceConfigModel).where(
                    ServiceConfigModel.service_name == _SERVICE_CONFIG_KEY
                )
            )
            row = result.scalar_one_or_none()
            if row:
                return row.config
            # Seed default config
            session.add(ServiceConfigModel(
                service_name=_SERVICE_CONFIG_KEY,
                config=DEFAULT_CONFIG,
            ))
            return DEFAULT_CONFIG

    # =========================================================================
    # TOPIC MANAGEMENT
    # =========================================================================

    async def list_topics(
        self, status: Optional[ResearchTopicStatus] = None
    ) -> List[ResearchTopic]:
        async with get_session() as session:
            stmt = select(ResearchTopicModel)
            if status:
                stmt = stmt.where(ResearchTopicModel.status == status.value)
            stmt = stmt.order_by(ResearchTopicModel.relevance_score.desc())
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [_topic_model_to_pydantic(r) for r in rows]

    async def get_topic(self, topic_id: str) -> Optional[ResearchTopic]:
        async with get_session() as session:
            result = await session.execute(
                select(ResearchTopicModel).where(ResearchTopicModel.id == topic_id)
            )
            row = result.scalar_one_or_none()
            if row:
                return _topic_model_to_pydantic(row)
            return None

    async def create_topic(self, topic_data: ResearchTopicCreate) -> ResearchTopic:
        topic_id = _generate_id("topic")
        async with get_session() as session:
            row = ResearchTopicModel(
                id=topic_id,
                name=topic_data.name,
                description=topic_data.description,
                search_queries=topic_data.search_queries,
                aspects=topic_data.aspects,
                category_tags=topic_data.category_tags,
                status=ResearchTopicStatus.ACTIVE.value,
                frequency=topic_data.frequency,
                findings_count=0,
                relevance_score=50.0,
            )
            session.add(row)
            logger.info("research_topic_created", topic_id=topic_id, name=topic_data.name)
            # Flush to ensure row is written before commit
            await session.flush()
            return _topic_model_to_pydantic(row)

    async def update_topic(
        self, topic_id: str, updates: ResearchTopicUpdate
    ) -> Optional[ResearchTopic]:
        async with get_session() as session:
            result = await session.execute(
                select(ResearchTopicModel).where(ResearchTopicModel.id == topic_id)
            )
            row = result.scalar_one_or_none()
            if not row:
                return None

            update_dict = updates.model_dump(exclude_unset=True)
            for key, value in update_dict.items():
                if value is not None:
                    if isinstance(value, ResearchTopicStatus):
                        setattr(row, key, value.value)
                    else:
                        setattr(row, key, value)

            await session.flush()
            logger.info("research_topic_updated", topic_id=topic_id)
            return _topic_model_to_pydantic(row)

    async def delete_topic(self, topic_id: str) -> bool:
        async with get_session() as session:
            result = await session.execute(
                delete(ResearchTopicModel).where(ResearchTopicModel.id == topic_id)
            )
            if result.rowcount > 0:
                logger.info("research_topic_deleted", topic_id=topic_id)
                return True
            return False

    async def seed_default_topics(self) -> List[ResearchTopic]:
        async with get_session() as session:
            # Get existing topic names
            result = await session.execute(
                select(ResearchTopicModel.name)
            )
            existing_names = {r[0] for r in result.all()}

            created = []
            for default in DEFAULT_TOPICS:
                if default["name"] in existing_names:
                    continue

                topic_id = _generate_id("topic")
                row = ResearchTopicModel(
                    id=topic_id,
                    name=default["name"],
                    description=default.get("description"),
                    search_queries=default.get("searchQueries", []),
                    aspects=default.get("aspects", []),
                    category_tags=default.get("categoryTags", []),
                    status=ResearchTopicStatus.ACTIVE.value,
                    frequency="daily",
                    findings_count=0,
                    relevance_score=50.0,
                )
                session.add(row)
                created.append(_topic_model_to_pydantic(row))

            if created:
                await session.flush()
            logger.info("research_topics_seeded", count=len(created))
            return created

    # =========================================================================
    # FINDING MANAGEMENT
    # =========================================================================

    async def list_findings(
        self,
        topic_id: Optional[str] = None,
        status: Optional[FindingStatus] = None,
        min_score: Optional[float] = None,
        limit: int = 50,
    ) -> List[ResearchFinding]:
        async with get_session() as session:
            stmt = select(ResearchFindingModel)
            if topic_id:
                stmt = stmt.where(ResearchFindingModel.topic_id == topic_id)
            if status:
                stmt = stmt.where(ResearchFindingModel.status == status.value)
            if min_score is not None:
                stmt = stmt.where(ResearchFindingModel.composite_score >= min_score)
            stmt = stmt.order_by(ResearchFindingModel.composite_score.desc())
            stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [_finding_model_to_pydantic(r) for r in rows]

    async def get_finding(self, finding_id: str) -> Optional[ResearchFinding]:
        async with get_session() as session:
            result = await session.execute(
                select(ResearchFindingModel).where(ResearchFindingModel.id == finding_id)
            )
            row = result.scalar_one_or_none()
            if row:
                return _finding_model_to_pydantic(row)
            return None

    async def review_finding(self, finding_id: str) -> Optional[ResearchFinding]:
        return await self._update_finding_status(
            finding_id, FindingStatus.REVIEWED, reviewed_at=datetime.now(timezone.utc)
        )

    async def dismiss_finding(self, finding_id: str) -> Optional[ResearchFinding]:
        result = await self._update_finding_status(finding_id, FindingStatus.DISMISSED)
        if result:
            await self.record_feedback(finding_id, "dismissed")
        return result

    async def create_task_from_finding(self, finding_id: str) -> Dict[str, Any]:
        """Create a Legion task from a research finding."""
        from app.services.legion_client import get_legion_client

        finding = await self.get_finding(finding_id)
        if not finding:
            return {"error": "Finding not found"}

        legion = get_legion_client()
        if not await legion.health_check():
            return {"error": "Legion unavailable"}

        sprint = await self._get_or_create_research_sprint(legion)
        if not sprint:
            return {"error": "Could not get or create research sprint"}

        task_title = finding.suggested_task or finding.title
        summary = finding.llm_summary or finding.snippet[:200]
        task_data = {
            "title": f"[Research] {task_title[:80]}",
            "prompt": f"Evaluate this research finding and decide if it's worth implementing: {summary}",
            "description": (
                f"Source: {finding.url}\n"
                f"Score: {finding.composite_score:.0f} "
                f"(relevance={finding.relevance_score:.0f}, "
                f"novelty={finding.novelty_score:.0f}, "
                f"action={finding.actionability_score:.0f})\n\n"
                f"Summary: {summary}\n\n"
                f"Evaluate this finding and decide if it's worth implementing."
            ),
            "priority": 3,
        }

        try:
            task = await legion.create_task(sprint["id"], task_data)
            task_id = str(task.get("id", ""))

            await self._update_finding_status(
                finding_id, FindingStatus.TASK_CREATED, linked_task_id=task_id
            )
            await self.record_feedback(finding_id, "created_task")

            logger.info("research_task_created", finding_id=finding_id, task_id=task_id)
            return {"task_id": task_id, "sprint_id": sprint["id"], "title": task_data["title"]}
        except Exception as e:
            logger.error("research_task_creation_failed", error=str(e))
            return {"error": str(e)}

    async def _update_finding_status(
        self, finding_id: str, new_status: FindingStatus, **extra_fields
    ) -> Optional[ResearchFinding]:
        async with get_session() as session:
            result = await session.execute(
                select(ResearchFindingModel).where(ResearchFindingModel.id == finding_id)
            )
            row = result.scalar_one_or_none()
            if not row:
                return None

            row.status = new_status.value
            for key, value in extra_fields.items():
                if hasattr(row, key):
                    setattr(row, key, value)

            await session.flush()
            return _finding_model_to_pydantic(row)

    # =========================================================================
    # RESEARCH EXECUTION
    # =========================================================================

    async def run_daily_cycle(self) -> ResearchCycleResult:
        """Execute the daily research cycle across all active topics."""
        config = await self._get_config()
        daily_cfg = config.get("daily", DEFAULT_CONFIG["daily"])
        weights = config.get("scoring_weights", DEFAULT_CONFIG["scoring_weights"])
        started_at = datetime.now(timezone.utc)

        logger.info("research_daily_cycle_start")

        # Load active daily topics
        topics = await self.list_topics(status=ResearchTopicStatus.ACTIVE)
        topics = [t for t in topics if t.frequency == "daily"]
        topics = topics[: daily_cfg.get("max_topics_per_cycle", 5)]

        total_results = 0
        all_new_findings = []
        duplicates_filtered = 0
        errors = []

        # Load existing URLs for dedup
        existing_urls = await self._get_existing_urls()

        searxng = get_searxng_service()
        max_results = daily_cfg.get("max_results_per_query", 10)

        for topic in topics:
            try:
                topic_results = await self._research_topic(
                    searxng, topic, max_results, existing_urls
                )
                total_results += topic_results["total"]
                all_new_findings.extend(topic_results["new"])
                duplicates_filtered += topic_results["duplicates"]
                existing_urls.update(topic_results["new_urls"])

                # Update topic metadata
                await self._mark_topic_researched(topic.id, len(topic_results["new"]))

            except Exception as e:
                logger.error("research_topic_failed", topic=topic.name, error=str(e))
                errors.append(f"{topic.name}: {str(e)}")

        # Score findings with heuristics in batches
        scored_findings = []
        if all_new_findings:
            scored_findings = await self._score_findings_batch(all_new_findings, weights)

        # Store scored findings
        high_value = []
        threshold = daily_cfg.get("high_value_threshold", 75)
        for finding in scored_findings:
            stored = await self._store_finding(finding)
            if stored and finding.get("compositeScore", 0) >= threshold:
                high_value.append(finding)

        # Auto-create Legion tasks for high-value findings
        max_tasks = daily_cfg.get("max_auto_tasks_per_cycle", 3)
        tasks_created = await self._auto_create_tasks(high_value[:max_tasks])

        # Send notification
        await self._notify_cycle_complete(
            len(topics), len(scored_findings), len(high_value), tasks_created
        )

        # Record cycle
        cycle_result = await self._record_cycle(
            started_at=started_at,
            topics_researched=len(topics),
            total_results=total_results,
            new_findings=len(scored_findings),
            duplicate_filtered=duplicates_filtered,
            high_value_findings=len(high_value),
            tasks_created=tasks_created,
            errors=errors,
        )

        logger.info(
            "research_daily_cycle_complete",
            topics=len(topics),
            findings=len(scored_findings),
            high_value=len(high_value),
            tasks=tasks_created,
        )

        return cycle_result

    async def run_weekly_deep_dive(self) -> ResearchCycleResult:
        """Weekly expanded research with deeper analysis and trend report."""
        config = await self._get_config()
        weekly_cfg = config.get("weekly", DEFAULT_CONFIG["weekly"])
        weights = config.get("scoring_weights", DEFAULT_CONFIG["scoring_weights"])
        started_at = datetime.now(timezone.utc)

        logger.info("research_weekly_deep_dive_start")

        topics = await self.list_topics(status=ResearchTopicStatus.ACTIVE)
        total_results = 0
        all_new_findings = []
        duplicates_filtered = 0
        errors = []
        existing_urls = await self._get_existing_urls()

        searxng = get_searxng_service()
        max_results = weekly_cfg.get("max_results_per_query", 15)
        extra_qualifiers = weekly_cfg.get("extra_qualifiers", [])

        for topic in topics:
            try:
                # Regular research
                topic_results = await self._research_topic(
                    searxng, topic, max_results, existing_urls
                )
                total_results += topic_results["total"]
                all_new_findings.extend(topic_results["new"])
                duplicates_filtered += topic_results["duplicates"]
                existing_urls.update(topic_results["new_urls"])

                # Expanded queries with extra qualifiers
                for qualifier in extra_qualifiers:
                    expanded_query = f"{topic.name} {qualifier}"
                    results = await searxng.search(expanded_query, num_results=max_results)
                    total_results += len(results)

                    for r in results:
                        if r.url in existing_urls:
                            duplicates_filtered += 1
                            continue
                        all_new_findings.append({
                            "topicId": topic.id,
                            "title": r.title,
                            "url": r.url,
                            "snippet": r.snippet,
                            "sourceEngine": r.engine,
                        })
                        existing_urls.add(r.url)

                    await asyncio.sleep(0.5)

                await self._mark_topic_researched(topic.id, len(topic_results["new"]))

            except Exception as e:
                logger.error("weekly_topic_failed", topic=topic.name, error=str(e))
                errors.append(f"{topic.name}: {str(e)}")

        # Score findings
        scored_findings = []
        if all_new_findings:
            scored_findings = await self._score_findings_batch(all_new_findings, weights)

        # Store
        high_value = []
        for finding in scored_findings:
            stored = await self._store_finding(finding)
            if stored and finding.get("compositeScore", 0) >= 75:
                high_value.append(finding)

        # Auto-create tasks (more generous on deep dive)
        tasks_created = await self._auto_create_tasks(high_value[:5])

        # Generate weekly trend report
        if weekly_cfg.get("generate_trend_report", True) and scored_findings:
            await self._generate_trend_report(scored_findings)

        await self._notify_cycle_complete(
            len(topics), len(scored_findings), len(high_value), tasks_created, deep_dive=True
        )

        cycle_result = await self._record_cycle(
            started_at=started_at,
            topics_researched=len(topics),
            total_results=total_results,
            new_findings=len(scored_findings),
            duplicate_filtered=duplicates_filtered,
            high_value_findings=len(high_value),
            tasks_created=tasks_created,
            errors=errors,
        )

        logger.info(
            "research_weekly_complete",
            findings=len(scored_findings),
            high_value=len(high_value),
            tasks=tasks_created,
        )

        return cycle_result

    async def research_single_topic(self, topic_id: str) -> List[ResearchFinding]:
        """Research a single topic on demand."""
        topic = await self.get_topic(topic_id)
        if not topic:
            return []

        config = await self._get_config()
        weights = config.get("scoring_weights", DEFAULT_CONFIG["scoring_weights"])
        existing_urls = await self._get_existing_urls()

        searxng = get_searxng_service()
        topic_results = await self._research_topic(searxng, topic, 10, existing_urls)

        scored = []
        if topic_results["new"]:
            scored = await self._score_findings_batch(topic_results["new"], weights)

        stored = []
        for finding in scored:
            result = await self._store_finding(finding)
            if result:
                stored.append(ResearchFinding(**finding))

        await self._mark_topic_researched(topic_id, len(stored))
        return stored

    # =========================================================================
    # KNOWLEDGE BASE
    # =========================================================================

    async def get_knowledge_summary(self, topic: Optional[str] = None) -> str:
        """Get a summary of accumulated research knowledge."""
        async with get_session() as session:
            stmt = select(ResearchFindingModel)
            if topic:
                topic_lower = f"%{topic.lower()}%"
                stmt = stmt.where(
                    or_(
                        ResearchFindingModel.topic_id.ilike(topic_lower),
                        ResearchFindingModel.title.ilike(topic_lower),
                    )
                )
            result = await session.execute(stmt)
            rows = result.scalars().all()

        if not rows:
            if topic:
                return f"No findings matching '{topic}'."
            return "No research findings yet. Run a research cycle first."

        total = len(rows)

        # Aggregate stats
        categories: Dict[str, int] = {}
        all_tags: Dict[str, int] = {}
        for r in rows:
            cat = r.category or "other"
            categories[cat] = categories.get(cat, 0) + 1
            for tag in (r.tags or []):
                all_tags[tag] = all_tags.get(tag, 0) + 1

        top_tags = sorted(all_tags.items(), key=lambda x: x[1], reverse=True)[:10]
        top_findings = sorted(rows, key=lambda x: x.composite_score or 0, reverse=True)[:5]

        lines = [f"Research Knowledge Base ({total} findings)\n"]
        lines.append("Categories: " + ", ".join(f"{k}: {v}" for k, v in categories.items()))
        lines.append("Trending tags: " + ", ".join(f"{t[0]} ({t[1]})" for t in top_tags))
        lines.append("\nTop discoveries:")
        for r in top_findings:
            score = r.composite_score or 0
            summary = r.llm_summary or r.title or ""
            lines.append(f"  [{score:.0f}] {summary}")

        return "\n".join(lines)

    async def search_knowledge(self, query: str, limit: int = 20) -> List[ResearchFinding]:
        """Search the knowledge base by text matching."""
        async with get_session() as session:
            query_pattern = f"%{query.lower()}%"
            stmt = (
                select(ResearchFindingModel)
                .where(
                    or_(
                        ResearchFindingModel.title.ilike(query_pattern),
                        ResearchFindingModel.snippet.ilike(query_pattern),
                        ResearchFindingModel.llm_summary.ilike(query_pattern),
                    )
                )
                .order_by(ResearchFindingModel.composite_score.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [_finding_model_to_pydantic(r) for r in rows]

    # =========================================================================
    # SELF-IMPROVEMENT
    # =========================================================================

    async def record_feedback(self, finding_id: str, action: str) -> None:
        """Record user feedback on a finding for self-improvement.
        Also propagates feedback to the rules engine for auto-learning."""
        finding = await self.get_finding(finding_id)

        # Propagate to rules engine
        try:
            from app.services.research_rules_service import get_research_rules_service
            rules_service = get_research_rules_service()
            was_useful = action in ("useful", "created_task")
            await rules_service.record_feedback(finding_id, was_useful)
        except Exception as e:
            logger.warning("Failed to propagate feedback to rules engine", error=str(e))

        async with get_session() as session:
            result = await session.execute(
                select(ServiceConfigModel).where(
                    ServiceConfigModel.service_name == _FEEDBACK_CONFIG_KEY
                )
            )
            row = result.scalar_one_or_none()
            if not row:
                row = ServiceConfigModel(
                    service_name=_FEEDBACK_CONFIG_KEY,
                    config={"feedback": []},
                )
                session.add(row)
                await session.flush()

            feedback_list = row.config.get("feedback", [])
            entry = {
                "findingId": finding_id,
                "action": action,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "topicId": finding.topic_id if finding else None,
            }
            feedback_list.append(entry)

            # Trim to retention limit
            max_feedback = DEFAULT_CONFIG["retention"]["max_feedback"]
            if len(feedback_list) > max_feedback:
                feedback_list = feedback_list[-max_feedback:]

            # JSONB mutation: assign new dict to trigger SQLAlchemy change detection
            row.config = {**row.config, "feedback": feedback_list}

    async def recalibrate_topics(self) -> Dict[str, Any]:
        """Adjust topic relevance scores based on user feedback."""
        async with get_session() as session:
            result = await session.execute(
                select(ServiceConfigModel).where(
                    ServiceConfigModel.service_name == _FEEDBACK_CONFIG_KEY
                )
            )
            row = result.scalar_one_or_none()

        feedback = []
        if row:
            feedback = row.config.get("feedback", [])

        if not feedback:
            return {"status": "no_feedback", "adjustments": []}

        topics = await self.list_topics()
        adjustments = []

        for topic in topics:
            topic_feedback = [f for f in feedback if f.get("topicId") == topic.id]
            if len(topic_feedback) < 3:
                continue

            useful = len([
                f for f in topic_feedback
                if f["action"] in ("useful", "created_task")
            ])
            not_useful = len([
                f for f in topic_feedback
                if f["action"] in ("not_useful", "dismissed")
            ])
            total = useful + not_useful
            if total == 0:
                continue

            usefulness_ratio = useful / total
            # Blend current score with feedback signal
            new_score = topic.relevance_score * 0.7 + (usefulness_ratio * 100) * 0.3
            new_score = round(max(0, min(100, new_score)), 1)

            update_fields: Dict[str, Any] = {"relevance_score": new_score}
            # Auto-pause topics scoring below 20
            if new_score < 20:
                update_fields["status"] = ResearchTopicStatus.PAUSED

            await self.update_topic(
                topic.id,
                ResearchTopicUpdate(**{k: v for k, v in update_fields.items()}),
            )
            adjustments.append({
                "topic": topic.name,
                "old_score": topic.relevance_score,
                "new_score": new_score,
                "feedback_count": total,
                "usefulness_ratio": round(usefulness_ratio, 2),
                "paused": new_score < 20,
            })

        # Suggest new queries from high-value findings
        suggested = await self._suggest_new_queries()

        logger.info("research_recalibrated", adjustments=len(adjustments))
        return {
            "status": "recalibrated",
            "adjustments": adjustments,
            "suggested_queries": suggested,
        }

    # =========================================================================
    # STATS
    # =========================================================================

    async def get_stats(self) -> ResearchStats:
        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)

        async with get_session() as session:
            # Total topics + active topics
            total_topics_q = await session.execute(
                select(sql_func.count()).select_from(ResearchTopicModel)
            )
            total_topics = total_topics_q.scalar() or 0

            active_topics_q = await session.execute(
                select(sql_func.count()).select_from(ResearchTopicModel).where(
                    ResearchTopicModel.status == "active"
                )
            )
            active_topics = active_topics_q.scalar() or 0

            # Total findings
            total_findings_q = await session.execute(
                select(sql_func.count()).select_from(ResearchFindingModel)
            )
            total_findings = total_findings_q.scalar() or 0

            # Findings this week
            findings_week_q = await session.execute(
                select(sql_func.count()).select_from(ResearchFindingModel).where(
                    ResearchFindingModel.discovered_at >= week_ago
                )
            )
            findings_this_week = findings_week_q.scalar() or 0

            # Tasks created total
            tasks_total_q = await session.execute(
                select(sql_func.count()).select_from(ResearchFindingModel).where(
                    ResearchFindingModel.status == "task_created"
                )
            )
            tasks_total = tasks_total_q.scalar() or 0

            # Tasks created this week
            tasks_week_q = await session.execute(
                select(sql_func.count()).select_from(ResearchFindingModel).where(
                    ResearchFindingModel.status == "task_created",
                    ResearchFindingModel.discovered_at >= week_ago,
                )
            )
            tasks_this_week = tasks_week_q.scalar() or 0

            # Average composite score
            avg_score_q = await session.execute(
                select(sql_func.avg(ResearchFindingModel.composite_score)).where(
                    ResearchFindingModel.composite_score.isnot(None)
                )
            )
            avg_score = avg_score_q.scalar() or 0

            # Top finding
            top_finding_q = await session.execute(
                select(ResearchFindingModel)
                .order_by(ResearchFindingModel.composite_score.desc())
                .limit(1)
            )
            top_row = top_finding_q.scalar_one_or_none()
            top_finding = None
            if top_row:
                top_finding = top_row.llm_summary or top_row.title

            # Last cycle
            last_cycle_q = await session.execute(
                select(ResearchCycleModel)
                .order_by(ResearchCycleModel.started_at.desc())
                .limit(1)
            )
            last_cycle_row = last_cycle_q.scalar_one_or_none()
            last_cycle_at = last_cycle_row.completed_at if last_cycle_row else None

        return ResearchStats(
            total_topics=total_topics,
            active_topics=active_topics,
            total_findings=total_findings,
            findings_this_week=findings_this_week,
            tasks_created_total=tasks_total,
            tasks_created_this_week=tasks_this_week,
            avg_relevance_score=round(avg_score, 1),
            top_finding=top_finding,
            last_cycle_at=last_cycle_at,
        )

    async def get_recent_cycles(self, limit: int = 10) -> List[ResearchCycleResult]:
        async with get_session() as session:
            result = await session.execute(
                select(ResearchCycleModel)
                .order_by(ResearchCycleModel.started_at.desc())
                .limit(limit)
            )
            rows = result.scalars().all()
            # Return in chronological order (oldest first)
            return [_cycle_model_to_pydantic(r) for r in reversed(rows)]

    # =========================================================================
    # INTERNAL HELPERS
    # =========================================================================

    async def _research_topic(
        self, searxng, topic: ResearchTopic, max_results: int, existing_urls: set
    ) -> Dict[str, Any]:
        """Execute search queries for a single topic."""
        all_results = []
        new_findings = []
        new_urls = set()
        duplicates = 0

        # Search each query
        for query in topic.search_queries:
            results = await searxng.search(query, num_results=max_results)
            all_results.extend(results)
            await asyncio.sleep(0.5)

        # Aspect-based research
        if topic.aspects:
            aspect_data = await searxng.research_topic(topic.name, topic.aspects)
            all_results.extend(aspect_data.get("all_results", []))

        # Dedup
        seen_urls = set()
        for r in all_results:
            url = r.url if hasattr(r, "url") else r.get("url", "")
            title = r.title if hasattr(r, "title") else r.get("title", "")
            snippet = r.snippet if hasattr(r, "snippet") else r.get("snippet", "")
            engine = r.engine if hasattr(r, "engine") else r.get("engine")

            if url in existing_urls or url in seen_urls:
                duplicates += 1
                continue

            # Basic title dedup (exact match)
            seen_urls.add(url)
            new_urls.add(url)

            new_findings.append({
                "topicId": topic.id,
                "title": title,
                "url": url,
                "snippet": snippet[:300] if snippet else "",
                "sourceEngine": engine,
            })

        return {
            "total": len(all_results),
            "new": new_findings,
            "duplicates": duplicates,
            "new_urls": new_urls,
        }

    async def _score_findings_batch(
        self, findings: List[Dict], weights: Dict[str, float]
    ) -> List[Dict]:
        """Score findings using heuristic analysis + dynamic rules engine.

        Two-layer scoring:
        1. Fast heuristic scoring (keyword-based, instant)
        2. Dynamic rules engine (JSONB rules from DB, modifies scores/categories/tags)
        """
        # Build topic map from DB
        async with get_session() as session:
            result = await session.execute(select(ResearchTopicModel))
            rows = result.scalars().all()
            topic_map = {
                r.id: {
                    "id": r.id,
                    "categoryTags": r.category_tags or [],
                    "searchQueries": r.search_queries or [],
                    "category_id": r.category_id,
                }
                for r in rows
            }

        # Layer 1: Heuristic scoring (fast, unchanged)
        scored = []
        for f in findings:
            finding = dict(f)
            topic = topic_map.get(f.get("topicId", ""), {})
            scores = self._heuristic_score(finding, topic, weights)
            finding.update(scores)
            scored.append(finding)

        # Layer 1.5: LLM-enhanced scoring for promising findings
        # Only call Ollama for findings that pass the heuristic threshold (perf optimization)
        try:
            from app.infrastructure.ollama_client import get_ollama_client
            client = get_ollama_client()
            for finding in scored:
                if finding.get("compositeScore", 0) >= 50:
                    llm_result = await self._llm_score_finding(client, finding)
                    if llm_result:
                        finding.update(llm_result)
        except Exception as e:
            logger.warning("llm_scoring_skipped", error=str(e))

        # Layer 2: Dynamic rules engine
        try:
            from app.services.research_rules_service import get_research_rules_service
            rules_service = get_research_rules_service()

            for finding in scored:
                eval_result = await rules_service.evaluate_rules(finding)
                if eval_result.rules_matched > 0:
                    finding.update(await rules_service.apply_rules(finding, eval_result))

                # Inherit category_id from topic if not set by rules
                if not finding.get("category_id"):
                    topic = topic_map.get(finding.get("topicId", ""), {})
                    if topic.get("category_id"):
                        finding["category_id"] = topic["category_id"]
        except Exception as e:
            logger.warning("Rules engine evaluation failed, using heuristic scores only", error=str(e))

        return scored

    async def _llm_score_finding(self, client, finding: Dict) -> Optional[Dict]:
        """Use Ollama to generate a better summary and refine scores for a finding.

        Only called for findings that pass the heuristic threshold (>=50 composite).
        Returns updated fields or None on failure.
        """
        import json as json_module

        title = finding.get("title", "")
        snippet = finding.get("snippet", "")
        url = finding.get("url", "")

        prompt = (
            f"Analyze this research finding for a personal AI assistant developer:\n"
            f"Title: {title}\n"
            f"URL: {url}\n"
            f"Snippet: {snippet[:300]}\n\n"
            f"Return ONLY a JSON object with:\n"
            f'- "summary": 2-sentence summary of why this is useful\n'
            f'- "relevance_adj": score adjustment -10 to +10\n'
            f'- "actionability_adj": score adjustment -10 to +10\n'
            f"No markdown, no explanation."
        )

        try:
            response = await client.chat_safe(
                prompt,
                task_type="analysis",
                temperature=0.1,
                num_predict=200,
                max_retries=1,
            )
            if not response:
                return None

            response = response.strip()
            # Extract JSON from response
            if "{" in response:
                json_str = response[response.index("{"):response.rindex("}") + 1]
                data = json_module.loads(json_str)

                result = {}
                if data.get("summary"):
                    result["llmSummary"] = data["summary"]

                rel_adj = data.get("relevance_adj", 0)
                act_adj = data.get("actionability_adj", 0)
                if rel_adj:
                    result["relevanceScore"] = min(95, max(10, finding.get("relevanceScore", 50) + rel_adj))
                if act_adj:
                    result["actionabilityScore"] = min(95, max(10, finding.get("actionabilityScore", 50) + act_adj))

                # Recompute composite if adjustments were made
                if rel_adj or act_adj:
                    result["compositeScore"] = round(
                        result.get("relevanceScore", finding.get("relevanceScore", 50)) * 0.35
                        + finding.get("noveltyScore", 50) * 0.25
                        + result.get("actionabilityScore", finding.get("actionabilityScore", 50)) * 0.40,
                        1,
                    )

                return result if result else None
        except Exception as e:
            logger.debug("llm_score_finding_failed", error=str(e), title=title[:50])
            return None

    def _heuristic_score(
        self, finding: Dict, topic: Dict, weights: Dict[str, float]
    ) -> Dict:
        """Compute heuristic scores for a single finding."""
        title = finding.get("title", "").lower()
        snippet = finding.get("snippet", "").lower()
        url = finding.get("url", "").lower()
        # Normalize hyphens so "open-source" matches "open source" etc.
        text = f"{title} {snippet}".replace("-", " ")

        # --- RELEVANCE SCORE (how relevant to Zero/AI assistants) ---
        relevance = 40  # base

        # High-value domain keywords
        high_rel = [
            "ai assistant", "personal assistant", "langgraph", "langchain",
            "agent", "multi agent", "orchestrat", "fastapi", "react",
            "ollama", "local llm", "self hosted", "mcp server", "tool use",
            "kanban", "task manag", "sprint", "chat ui", "chat interface",
            "framework", "workflow", "automation",
        ]
        for kw in high_rel:
            if kw in text:
                relevance += 7

        # Topic-specific keyword matching
        topic_keywords = topic.get("categoryTags", []) + topic.get("searchQueries", [])
        for kw in topic_keywords:
            if kw.lower().replace("-", " ") in text:
                relevance += 4

        relevance = min(95, relevance)

        # --- NOVELTY SCORE (how new/unique) ---
        novelty = 45  # base

        # Recency signals
        recency_signals = ["2026", "2025", "new", "latest", "release", "launch", "announce", "just"]
        for sig in recency_signals:
            if sig in text:
                novelty += 6

        # GitHub signals (repos are often novel/actionable)
        if "github.com" in url:
            novelty += 12
        if "arxiv.org" in url:
            novelty += 10

        # Uniqueness: longer snippets suggest richer content
        if len(snippet) > 200:
            novelty += 5
        if len(snippet) > 100:
            novelty += 3

        novelty = min(95, novelty)

        # --- ACTIONABILITY SCORE (can we act on this?) ---
        actionability = 35  # base

        action_signals = [
            "open source", "github", "repo", "library", "framework",
            "plugin", "template", "example", "tutorial", "how to",
            "install", "setup", "docker", "pip install", "npm",
            "api", "sdk", "integration", "self host",
        ]
        for sig in action_signals:
            if sig in text:
                actionability += 6

        # GitHub repos are highly actionable
        if "github.com" in url and ("/" in url.replace("github.com/", "", 1)):
            actionability += 12

        # Code-related content
        code_signals = ["python", "typescript", "javascript", "node", "rust"]
        for sig in code_signals:
            if sig in text:
                actionability += 5

        actionability = min(95, actionability)

        # --- COMPOSITE ---
        composite = (
            relevance * weights.get("relevance", 0.35)
            + novelty * weights.get("novelty", 0.25)
            + actionability * weights.get("actionability", 0.40)
        )

        # --- CATEGORY DETECTION ---
        category = "other"
        if "github.com" in url:
            category = "repo"
        elif any(kw in text for kw in ["pattern", "best practice", "architecture"]):
            category = "pattern"
        elif any(kw in text for kw in ["library", "framework", "sdk"]):
            category = "tool"
        elif any(kw in text for kw in ["technique", "method", "approach", "algorithm"]):
            category = "technique"
        elif any(kw in text for kw in ["project", "built", "building", "showcase"]):
            category = "project"
        elif "arxiv.org" in url or any(kw in text for kw in ["paper", "research", "study"]):
            category = "article"

        # --- AUTO-TAG ---
        tags = []
        tag_map = {
            "langgraph": ["langgraph"], "langchain": ["langchain"],
            "react": ["react", "frontend"], "fastapi": ["fastapi", "backend"],
            "ollama": ["ollama", "local-llm"], "docker": ["docker"],
            "mcp": ["mcp"], "agent": ["agents"], "plugin": ["plugins"],
            "chat": ["chat-ui"], "kanban": ["kanban"], "whisper": ["audio"],
            "github": ["open-source"],
        }
        for trigger, tag_list in tag_map.items():
            if trigger in text:
                tags.extend(tag_list)
        tags = list(dict.fromkeys(tags))[:5]  # Deduplicate, limit 5

        # --- SUGGESTED TASK ---
        suggested_task = None
        if composite >= 60:
            if category == "repo":
                suggested_task = f"Evaluate repo: {finding.get('title', '')[:60]}"
            elif category == "tool":
                suggested_task = f"Test tool: {finding.get('title', '')[:60]}"
            elif category == "pattern":
                suggested_task = f"Study pattern: {finding.get('title', '')[:60]}"
            else:
                suggested_task = f"Review: {finding.get('title', '')[:60]}"

        # --- SUMMARY ---
        summary = snippet[:120].strip() if snippet else title[:120]
        if summary and not summary.endswith("."):
            summary = summary.rstrip() + "..."

        return {
            "relevanceScore": relevance,
            "noveltyScore": novelty,
            "actionabilityScore": actionability,
            "compositeScore": round(composite, 1),
            "category": category,
            "llmSummary": summary,
            "tags": tags,
            "suggestedTask": suggested_task,
        }

    async def _store_finding(self, finding: Dict) -> bool:
        """Store a scored finding to the database."""
        # Normalize category
        category = finding.get("category", "other").lower()
        if category not in [c.value for c in FindingCategory]:
            category = "other"

        finding_id = _generate_id("finding")

        # Generate embedding for semantic deduplication and search
        embedding = None
        try:
            from app.infrastructure.ollama_client import get_ollama_client
            embed_text = f"{finding.get('title', '')} {finding.get('snippet', '')[:200]}"
            embedding = await get_ollama_client().embed_safe(embed_text)
        except Exception:
            pass

        async with get_session() as session:
            row = ResearchFindingModel(
                id=finding_id,
                topic_id=finding.get("topicId"),
                title=finding.get("title", ""),
                url=finding.get("url", ""),
                snippet=finding.get("snippet", ""),
                source_engine=finding.get("sourceEngine"),
                category=category,
                status=FindingStatus.NEW.value,
                relevance_score=finding.get("relevanceScore", 50),
                novelty_score=finding.get("noveltyScore", 50),
                actionability_score=finding.get("actionabilityScore", 50),
                composite_score=finding.get("compositeScore", 50),
                llm_summary=finding.get("llmSummary"),
                tags=finding.get("tags", []),
                suggested_task=finding.get("suggestedTask"),
                linked_task_id=None,
                category_id=finding.get("category_id"),
                fired_rule_ids=finding.get("fired_rule_ids", []),
                embedding=embedding,
                discovered_at=datetime.now(timezone.utc),
            )
            session.add(row)

        # Enforce retention limit: delete oldest findings beyond max
        max_findings = DEFAULT_CONFIG["retention"]["max_findings"]
        async with get_session() as session:
            count_q = await session.execute(
                select(sql_func.count()).select_from(ResearchFindingModel)
            )
            total = count_q.scalar() or 0
            if total > max_findings:
                excess = total - max_findings
                # Find IDs of oldest excess findings
                oldest_q = await session.execute(
                    select(ResearchFindingModel.id)
                    .order_by(ResearchFindingModel.discovered_at.asc())
                    .limit(excess)
                )
                old_ids = [r[0] for r in oldest_q.all()]
                if old_ids:
                    await session.execute(
                        delete(ResearchFindingModel).where(
                            ResearchFindingModel.id.in_(old_ids)
                        )
                    )

        # Store the generated ID back for auto-task creation reference
        finding["id"] = finding_id
        return True

    async def _auto_create_tasks(self, high_value_findings: List[Dict]) -> int:
        """Auto-create Legion tasks for high-value findings."""
        if not high_value_findings:
            return 0

        from app.services.legion_client import get_legion_client

        try:
            legion = get_legion_client()
            if not await legion.health_check():
                logger.warning("legion_unavailable_for_research_tasks")
                return 0
        except Exception:
            return 0

        sprint = await self._get_or_create_research_sprint(legion)
        if not sprint:
            return 0

        tasks_created = 0
        for finding in high_value_findings:
            task_title = finding.get("suggestedTask") or finding.get("title", "")
            summary = finding.get("llmSummary", finding.get("snippet", "")[:200])
            task_data = {
                "title": f"[Research] {task_title[:80]}",
                "prompt": f"Evaluate this research finding and decide if it's worth implementing: {summary}",
                "description": (
                    f"Source: {finding.get('url', '')}\n"
                    f"Score: {finding.get('compositeScore', 0):.0f}\n\n"
                    f"Summary: {summary}\n\n"
                    f"Evaluate this finding and decide if it's worth implementing."
                ),
                "priority": 3,
                "order": tasks_created + 1,
            }

            try:
                task = await legion.create_task(sprint["id"], task_data)
                task_id = str(task.get("id", ""))

                # Update finding status
                finding_id = finding.get("id")
                if finding_id:
                    await self._update_finding_status(
                        finding_id, FindingStatus.TASK_CREATED, linked_task_id=task_id
                    )
                tasks_created += 1
            except Exception as e:
                logger.warning("research_auto_task_failed", error=str(e))

        return tasks_created

    async def _get_or_create_research_sprint(self, legion) -> Optional[Dict]:
        """Get active sprint or create one for research tasks."""
        try:
            # Try to find existing active or planned sprint for research
            current = await legion.get_current_sprint(ZERO_PROJECT_ID)
            if current:
                return current

            # No active sprint, check for planned research sprint
            sprints = await legion.list_sprints(
                project_id=ZERO_PROJECT_ID, status="planned", limit=5
            )
            for s in sprints:
                if "research" in s.get("name", "").lower():
                    return s

            # Create a new research sprint (Legion defaults to "planned" status)
            sprint_data = {
                "name": f"S69: Research Discoveries - {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                "description": "Auto-created sprint for research agent discoveries",
                "project_id": ZERO_PROJECT_ID,
                "priority": 3,
            }
            return await legion.create_sprint(sprint_data)
        except Exception as e:
            logger.warning("research_sprint_failed", error=str(e))
            return None

    async def _get_existing_urls(self) -> set:
        """Load all existing finding URLs for deduplication."""
        async with get_session() as session:
            result = await session.execute(
                select(ResearchFindingModel.url)
            )
            return {r[0] for r in result.all() if r[0]}

    async def _mark_topic_researched(self, topic_id: str, new_count: int) -> None:
        """Update topic's last researched timestamp and findings count."""
        async with get_session() as session:
            result = await session.execute(
                select(ResearchTopicModel).where(ResearchTopicModel.id == topic_id)
            )
            row = result.scalar_one_or_none()
            if row:
                row.last_researched_at = datetime.now(timezone.utc)
                row.findings_count = (row.findings_count or 0) + new_count

    async def _record_cycle(self, **kwargs) -> ResearchCycleResult:
        """Record a research cycle result."""
        cycle_id = _generate_id("cycle")
        now = datetime.now(timezone.utc)

        async with get_session() as session:
            row = ResearchCycleModel(
                id=cycle_id,
                started_at=kwargs["started_at"],
                completed_at=now,
                topics_researched=kwargs.get("topics_researched", 0),
                total_results=kwargs.get("total_results", 0),
                new_findings=kwargs.get("new_findings", 0),
                duplicate_filtered=kwargs.get("duplicate_filtered", 0),
                high_value_findings=kwargs.get("high_value_findings", 0),
                tasks_created=kwargs.get("tasks_created", 0),
                errors=kwargs.get("errors", []),
            )
            session.add(row)

            # Enforce retention limit
            max_cycles = DEFAULT_CONFIG["retention"]["max_cycles"]
            count_q = await session.execute(
                select(sql_func.count()).select_from(ResearchCycleModel)
            )
            total = count_q.scalar() or 0
            if total > max_cycles:
                excess = total - max_cycles
                oldest_q = await session.execute(
                    select(ResearchCycleModel.id)
                    .order_by(ResearchCycleModel.started_at.asc())
                    .limit(excess)
                )
                old_ids = [r[0] for r in oldest_q.all()]
                if old_ids:
                    await session.execute(
                        delete(ResearchCycleModel).where(
                            ResearchCycleModel.id.in_(old_ids)
                        )
                    )

        return ResearchCycleResult(
            cycle_id=cycle_id,
            started_at=kwargs["started_at"],
            completed_at=now,
            topics_researched=kwargs.get("topics_researched", 0),
            total_results=kwargs.get("total_results", 0),
            new_findings=kwargs.get("new_findings", 0),
            duplicate_filtered=kwargs.get("duplicate_filtered", 0),
            high_value_findings=kwargs.get("high_value_findings", 0),
            tasks_created=kwargs.get("tasks_created", 0),
            errors=kwargs.get("errors", []),
        )

    async def _notify_cycle_complete(
        self,
        topics_count: int,
        findings_count: int,
        high_value_count: int,
        tasks_created: int,
        deep_dive: bool = False,
    ) -> None:
        """Send Discord notification about research cycle results."""
        try:
            from app.services.notification_service import get_notification_service

            cycle_type = "Weekly Deep Dive" if deep_dive else "Daily Cycle"
            lines = [f"**Research Agent - {cycle_type}**\n"]
            lines.append(f"Topics scanned: {topics_count}")
            lines.append(f"New findings: {findings_count}")
            lines.append(f"High-value: {high_value_count}")
            lines.append(f"Tasks created: {tasks_created}")

            notification_svc = get_notification_service()
            await notification_svc.create_notification(
                title=f"Research Agent - {cycle_type}",
                message="\n".join(lines),
                channel="discord",
                source="research_agent",
            )
        except Exception as e:
            logger.warning("research_notification_failed", error=str(e))

    async def _suggest_new_queries(self) -> List[str]:
        """Suggest new search queries based on high-value finding tags and categories."""
        high_value = await self.list_findings(min_score=70, limit=15)
        if not high_value:
            return []

        # Extract most common tags from high-value findings
        tag_counts: Dict[str, int] = {}
        for f in high_value:
            for tag in f.tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

        top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        # Generate queries combining top tags with recency
        suggestions = []
        for tag, _ in top_tags:
            suggestions.append(f"{tag} open source 2026 new")

        return suggestions[:5]

    async def _generate_trend_report(self, findings: List[Dict]) -> None:
        """Generate a weekly trend report in markdown."""
        reports_dir = get_research_path() / "weekly_reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc)
        week_num = now.isocalendar()[1]
        filename = f"{now.year}-W{week_num:02d}.md"

        # Group findings by category
        by_category: Dict[str, List[Dict]] = {}
        for f in findings:
            cat = f.get("category", "other")
            by_category.setdefault(cat, []).append(f)

        lines = [
            f"# Weekly Research Report - {now.strftime('%Y-%m-%d')}",
            f"\nTotal findings: {len(findings)}",
            "",
        ]

        for cat, cat_findings in sorted(by_category.items()):
            lines.append(f"## {cat.title()} ({len(cat_findings)})")
            top = sorted(cat_findings, key=lambda x: x.get("compositeScore", 0), reverse=True)[:5]
            for f in top:
                score = f.get("compositeScore", 0)
                summary = f.get("llmSummary", f.get("title", ""))
                url = f.get("url", "")
                lines.append(f"- **[{score:.0f}]** {summary}")
                if url:
                    lines.append(f"  {url}")
            lines.append("")

        report_path = reports_dir / filename
        report_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("weekly_report_generated", filename=filename)


@lru_cache()
def get_research_service() -> ResearchService:
    """Get cached ResearchService instance."""
    return ResearchService()
