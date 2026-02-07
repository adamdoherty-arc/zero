"""
Research Agent Service.
Autonomous web research, discovery scoring, knowledge accumulation, and self-improvement.
"""

import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from functools import lru_cache
import structlog

from app.infrastructure.storage import JsonStorage
from app.infrastructure.config import get_settings, get_workspace_path
from app.models.research import (
    ResearchTopic, ResearchTopicCreate, ResearchTopicUpdate,
    ResearchTopicStatus, ResearchFinding, FindingStatus, FindingCategory,
    ResearchCycleResult, ResearchStats, FeedbackEntry,
)
from app.services.searxng_service import get_searxng_service

logger = structlog.get_logger()

# Zero project ID in Legion
ZERO_PROJECT_ID = 7

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
        "model": "qwen3:8b",  # Faster model for batch scoring (CPU-friendly)
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


def get_research_path():
    return get_workspace_path("research")


class ResearchService:
    """
    Autonomous research agent that discovers, scores, and tracks
    external developments relevant to Zero's improvement.
    """

    def __init__(self):
        self.storage = JsonStorage(get_research_path())
        self.settings = get_settings()
        self._topics_file = "topics.json"
        self._findings_file = "findings.json"
        self._cycles_file = "cycles.json"
        self._feedback_file = "feedback.json"
        self._config_file = "config.json"

    # =========================================================================
    # CONFIGURATION
    # =========================================================================

    async def _get_config(self) -> Dict[str, Any]:
        data = await self.storage.read(self._config_file)
        if not data:
            await self.storage.write(self._config_file, DEFAULT_CONFIG)
            return DEFAULT_CONFIG
        return data

    # =========================================================================
    # TOPIC MANAGEMENT
    # =========================================================================

    async def list_topics(
        self, status: Optional[ResearchTopicStatus] = None
    ) -> List[ResearchTopic]:
        data = await self.storage.read(self._topics_file)
        topics = data.get("topics", [])

        filtered = []
        for t in topics:
            if status and t.get("status") != status.value:
                continue
            filtered.append(t)

        return [ResearchTopic(**t) for t in filtered]

    async def get_topic(self, topic_id: str) -> Optional[ResearchTopic]:
        data = await self.storage.read(self._topics_file)
        for t in data.get("topics", []):
            if t.get("id") == topic_id:
                return ResearchTopic(**t)
        return None

    async def create_topic(self, topic_data: ResearchTopicCreate) -> ResearchTopic:
        data = await self.storage.read(self._topics_file)
        if "topics" not in data:
            data["topics"] = []
            data["nextTopicId"] = 1

        topic_id = f"topic-{data.get('nextTopicId', 1)}"
        data["nextTopicId"] = data.get("nextTopicId", 1) + 1

        topic = {
            "id": topic_id,
            "name": topic_data.name,
            "description": topic_data.description,
            "searchQueries": topic_data.search_queries,
            "aspects": topic_data.aspects,
            "categoryTags": topic_data.category_tags,
            "status": ResearchTopicStatus.ACTIVE.value,
            "frequency": topic_data.frequency,
            "lastResearchedAt": None,
            "findingsCount": 0,
            "relevanceScore": 50.0,
        }

        data["topics"].append(topic)
        await self.storage.write(self._topics_file, data)
        logger.info("research_topic_created", topic_id=topic_id, name=topic_data.name)
        return ResearchTopic(**topic)

    async def update_topic(
        self, topic_id: str, updates: ResearchTopicUpdate
    ) -> Optional[ResearchTopic]:
        data = await self.storage.read(self._topics_file)

        for i, t in enumerate(data.get("topics", [])):
            if t.get("id") == topic_id:
                update_dict = updates.model_dump(exclude_unset=True)
                for key, value in update_dict.items():
                    if value is not None:
                        # Convert snake_case to camelCase for storage
                        storage_key = self._to_camel_case(key)
                        if isinstance(value, ResearchTopicStatus):
                            t[storage_key] = value.value
                        else:
                            t[storage_key] = value

                data["topics"][i] = t
                await self.storage.write(self._topics_file, data)
                logger.info("research_topic_updated", topic_id=topic_id)
                return ResearchTopic(**t)

        return None

    async def delete_topic(self, topic_id: str) -> bool:
        data = await self.storage.read(self._topics_file)
        original = len(data.get("topics", []))
        data["topics"] = [t for t in data.get("topics", []) if t.get("id") != topic_id]
        if len(data["topics"]) < original:
            await self.storage.write(self._topics_file, data)
            logger.info("research_topic_deleted", topic_id=topic_id)
            return True
        return False

    async def seed_default_topics(self) -> List[ResearchTopic]:
        data = await self.storage.read(self._topics_file)
        if "topics" not in data:
            data["topics"] = []
            data["nextTopicId"] = 1

        existing_names = {t.get("name") for t in data["topics"]}
        created = []

        for default in DEFAULT_TOPICS:
            if default["name"] in existing_names:
                continue

            topic_id = f"topic-{data.get('nextTopicId', 1)}"
            data["nextTopicId"] = data.get("nextTopicId", 1) + 1

            topic = {
                "id": topic_id,
                "name": default["name"],
                "description": default.get("description"),
                "searchQueries": default.get("searchQueries", []),
                "aspects": default.get("aspects", []),
                "categoryTags": default.get("categoryTags", []),
                "status": ResearchTopicStatus.ACTIVE.value,
                "frequency": "daily",
                "lastResearchedAt": None,
                "findingsCount": 0,
                "relevanceScore": 50.0,
            }
            data["topics"].append(topic)
            created.append(ResearchTopic(**topic))

        await self.storage.write(self._topics_file, data)
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
        data = await self.storage.read(self._findings_file)
        findings = data.get("findings", [])

        filtered = []
        for f in findings:
            if topic_id and f.get("topicId") != topic_id:
                continue
            if status and f.get("status") != status.value:
                continue
            if min_score and f.get("compositeScore", 0) < min_score:
                continue
            filtered.append(f)

        filtered.sort(key=lambda x: x.get("compositeScore", 0), reverse=True)
        return [ResearchFinding(**f) for f in filtered[:limit]]

    async def get_finding(self, finding_id: str) -> Optional[ResearchFinding]:
        data = await self.storage.read(self._findings_file)
        for f in data.get("findings", []):
            if f.get("id") == finding_id:
                return ResearchFinding(**f)
        return None

    async def review_finding(self, finding_id: str) -> Optional[ResearchFinding]:
        return await self._update_finding_status(
            finding_id, FindingStatus.REVIEWED, reviewed_at=datetime.utcnow().isoformat()
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
        data = await self.storage.read(self._findings_file)
        for i, f in enumerate(data.get("findings", [])):
            if f.get("id") == finding_id:
                f["status"] = new_status.value
                for key, value in extra_fields.items():
                    storage_key = self._to_camel_case(key)
                    f[storage_key] = value
                data["findings"][i] = f
                await self.storage.write(self._findings_file, data)
                return ResearchFinding(**f)
        return None

    # =========================================================================
    # RESEARCH EXECUTION
    # =========================================================================

    async def run_daily_cycle(self) -> ResearchCycleResult:
        """Execute the daily research cycle across all active topics."""
        config = await self._get_config()
        daily_cfg = config.get("daily", DEFAULT_CONFIG["daily"])
        weights = config.get("scoring_weights", DEFAULT_CONFIG["scoring_weights"])
        started_at = datetime.utcnow()

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

        # Score findings with LLM in batches
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
        started_at = datetime.utcnow()

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
        data = await self.storage.read(self._findings_file)
        findings = data.get("findings", [])

        if not findings:
            return "No research findings yet. Run a research cycle first."

        if topic:
            topic_lower = topic.lower()
            findings = [
                f for f in findings
                if topic_lower in f.get("topicId", "").lower()
                or topic_lower in " ".join(f.get("tags", [])).lower()
                or topic_lower in f.get("title", "").lower()
            ]

        total = len(findings)
        if total == 0:
            return f"No findings matching '{topic}'."

        # Aggregate stats
        categories = {}
        all_tags = {}
        for f in findings:
            cat = f.get("category", "other")
            categories[cat] = categories.get(cat, 0) + 1
            for tag in f.get("tags", []):
                all_tags[tag] = all_tags.get(tag, 0) + 1

        top_tags = sorted(all_tags.items(), key=lambda x: x[1], reverse=True)[:10]
        top_findings = sorted(findings, key=lambda x: x.get("compositeScore", 0), reverse=True)[:5]

        lines = [f"Research Knowledge Base ({total} findings)\n"]
        lines.append("Categories: " + ", ".join(f"{k}: {v}" for k, v in categories.items()))
        lines.append("Trending tags: " + ", ".join(f"{t[0]} ({t[1]})" for t in top_tags))
        lines.append("\nTop discoveries:")
        for f in top_findings:
            score = f.get("compositeScore", 0)
            summary = f.get("llmSummary", f.get("title", ""))
            lines.append(f"  [{score:.0f}] {summary}")

        return "\n".join(lines)

    async def search_knowledge(self, query: str, limit: int = 20) -> List[ResearchFinding]:
        """Search the knowledge base by text matching."""
        data = await self.storage.read(self._findings_file)
        query_lower = query.lower()

        matches = []
        for f in data.get("findings", []):
            text = " ".join([
                f.get("title", ""),
                f.get("snippet", ""),
                f.get("llmSummary", ""),
                " ".join(f.get("tags", [])),
            ]).lower()
            if query_lower in text:
                matches.append(f)

        matches.sort(key=lambda x: x.get("compositeScore", 0), reverse=True)
        return [ResearchFinding(**f) for f in matches[:limit]]

    # =========================================================================
    # SELF-IMPROVEMENT
    # =========================================================================

    async def record_feedback(self, finding_id: str, action: str) -> None:
        """Record user feedback on a finding for self-improvement."""
        finding = await self.get_finding(finding_id)
        data = await self.storage.read(self._feedback_file)
        if "feedback" not in data:
            data["feedback"] = []

        entry = {
            "findingId": finding_id,
            "action": action,
            "timestamp": datetime.utcnow().isoformat(),
            "topicId": finding.topic_id if finding else None,
        }
        data["feedback"].append(entry)

        # Trim to retention limit
        max_feedback = DEFAULT_CONFIG["retention"]["max_feedback"]
        if len(data["feedback"]) > max_feedback:
            data["feedback"] = data["feedback"][-max_feedback:]

        await self.storage.write(self._feedback_file, data)

    async def recalibrate_topics(self) -> Dict[str, Any]:
        """Adjust topic relevance scores based on user feedback."""
        feedback_data = await self.storage.read(self._feedback_file)
        feedback = feedback_data.get("feedback", [])
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

            update_fields = {"relevance_score": new_score}
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
        topics_data = await self.storage.read(self._topics_file)
        findings_data = await self.storage.read(self._findings_file)
        cycles_data = await self.storage.read(self._cycles_file)

        topics = topics_data.get("topics", [])
        findings = findings_data.get("findings", [])
        cycles = cycles_data.get("cycles", [])

        now = datetime.utcnow()
        week_ago = (now - timedelta(days=7)).isoformat()

        active_topics = len([t for t in topics if t.get("status") == "active"])
        findings_this_week = len([
            f for f in findings if f.get("discoveredAt", "") >= week_ago
        ])
        tasks_total = len([f for f in findings if f.get("status") == "task_created"])
        tasks_this_week = len([
            f for f in findings
            if f.get("status") == "task_created" and f.get("discoveredAt", "") >= week_ago
        ])

        scores = [f.get("compositeScore", 0) for f in findings if f.get("compositeScore")]
        avg_score = sum(scores) / len(scores) if scores else 0

        top = None
        if findings:
            best = max(findings, key=lambda x: x.get("compositeScore", 0))
            top = best.get("llmSummary") or best.get("title")

        last_cycle = cycles[-1] if cycles else None
        last_cycle_at = last_cycle.get("completedAt") if last_cycle else None

        return ResearchStats(
            totalTopics=len(topics),
            activeTopics=active_topics,
            totalFindings=len(findings),
            findingsThisWeek=findings_this_week,
            tasksCreatedTotal=tasks_total,
            tasksCreatedThisWeek=tasks_this_week,
            avgRelevanceScore=round(avg_score, 1),
            topFinding=top,
            lastCycleAt=last_cycle_at,
        )

    async def get_recent_cycles(self, limit: int = 10) -> List[ResearchCycleResult]:
        data = await self.storage.read(self._cycles_file)
        cycles = data.get("cycles", [])
        return [ResearchCycleResult(**c) for c in cycles[-limit:]]

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
        """Score findings using heuristic analysis (instant, no LLM needed).

        Heuristic scoring produces differentiated scores (30-90 range) based on:
        - URL domain signals (github, arxiv, etc.)
        - Title/snippet keyword density for topic relevance
        - Source quality indicators
        - Content actionability signals
        """
        topics_data = await self.storage.read(self._topics_file)
        topic_map = {t["id"]: t for t in topics_data.get("topics", [])}

        scored = []
        for f in findings:
            finding = dict(f)
            topic = topic_map.get(f.get("topicId", ""), {})
            scores = self._heuristic_score(finding, topic, weights)
            finding.update(scores)
            scored.append(finding)

        return scored

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
        """Store a scored finding to findings.json."""
        data = await self.storage.read(self._findings_file)
        if "findings" not in data:
            data["findings"] = []
            data["nextFindingId"] = 1

        finding_id = f"finding-{data.get('nextFindingId', 1)}"
        data["nextFindingId"] = data.get("nextFindingId", 1) + 1

        # Normalize category
        category = finding.get("category", "other").lower()
        if category not in [c.value for c in FindingCategory]:
            category = "other"

        stored = {
            "id": finding_id,
            "topicId": finding.get("topicId"),
            "title": finding.get("title", ""),
            "url": finding.get("url", ""),
            "snippet": finding.get("snippet", ""),
            "sourceEngine": finding.get("sourceEngine"),
            "category": category,
            "status": FindingStatus.NEW.value,
            "relevanceScore": finding.get("relevanceScore", 50),
            "noveltyScore": finding.get("noveltyScore", 50),
            "actionabilityScore": finding.get("actionabilityScore", 50),
            "compositeScore": finding.get("compositeScore", 50),
            "llmSummary": finding.get("llmSummary"),
            "tags": finding.get("tags", []),
            "suggestedTask": finding.get("suggestedTask"),
            "linkedTaskId": None,
            "discoveredAt": datetime.utcnow().isoformat(),
            "reviewedAt": None,
        }

        data["findings"].append(stored)

        # Enforce retention limit
        max_findings = DEFAULT_CONFIG["retention"]["max_findings"]
        if len(data["findings"]) > max_findings:
            data["findings"] = data["findings"][-max_findings:]

        await self.storage.write(self._findings_file, data)
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
                "name": f"S69: Research Discoveries - {datetime.utcnow().strftime('%Y-%m-%d')}",
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
        data = await self.storage.read(self._findings_file)
        return {f.get("url", "") for f in data.get("findings", [])}

    async def _mark_topic_researched(self, topic_id: str, new_count: int) -> None:
        """Update topic's last researched timestamp and findings count."""
        data = await self.storage.read(self._topics_file)
        for t in data.get("topics", []):
            if t.get("id") == topic_id:
                t["lastResearchedAt"] = datetime.utcnow().isoformat()
                t["findingsCount"] = t.get("findingsCount", 0) + new_count
                break
        await self.storage.write(self._topics_file, data)

    async def _record_cycle(self, **kwargs) -> ResearchCycleResult:
        """Record a research cycle result."""
        data = await self.storage.read(self._cycles_file)
        if "cycles" not in data:
            data["cycles"] = []
            data["nextCycleId"] = 1

        cycle_id = f"cycle-{data.get('nextCycleId', 1)}"
        data["nextCycleId"] = data.get("nextCycleId", 1) + 1

        cycle = {
            "cycleId": cycle_id,
            "startedAt": kwargs["started_at"].isoformat(),
            "completedAt": datetime.utcnow().isoformat(),
            "topicsResearched": kwargs.get("topics_researched", 0),
            "totalResults": kwargs.get("total_results", 0),
            "newFindings": kwargs.get("new_findings", 0),
            "duplicateFiltered": kwargs.get("duplicate_filtered", 0),
            "highValueFindings": kwargs.get("high_value_findings", 0),
            "tasksCreated": kwargs.get("tasks_created", 0),
            "errors": kwargs.get("errors", []),
        }

        data["cycles"].append(cycle)

        # Trim cycles
        max_cycles = DEFAULT_CONFIG["retention"]["max_cycles"]
        if len(data["cycles"]) > max_cycles:
            data["cycles"] = data["cycles"][-max_cycles:]

        await self.storage.write(self._cycles_file, data)
        return ResearchCycleResult(**cycle)

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
        tag_counts = {}
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
        import os

        reports_dir = get_research_path() / "weekly_reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.utcnow()
        week_num = now.isocalendar()[1]
        filename = f"{now.year}-W{week_num:02d}.md"

        # Group findings by category
        by_category = {}
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

    @staticmethod
    def _to_camel_case(snake_str: str) -> str:
        """Convert snake_case to camelCase."""
        components = snake_str.split("_")
        return components[0] + "".join(x.title() for x in components[1:])


@lru_cache()
def get_research_service() -> ResearchService:
    """Get cached ResearchService instance."""
    return ResearchService()
