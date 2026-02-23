"""
Money Maker Service.
Generates, researches, ranks, and tracks money-making ideas using LLM + web research.

Persists data to PostgreSQL via SQLAlchemy async ORM.
"""

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from functools import lru_cache
import structlog

from sqlalchemy import select, func

from app.infrastructure.database import get_session
from app.infrastructure.config import get_settings
from app.db.models import MoneyIdeaModel, ServiceConfigModel
from app.models.money_maker import (
    MoneyIdea, MoneyIdeaCreate, MoneyIdeaUpdate, MoneyIdeaAction,
    IdeaStatus, IdeaCategory, TimeToROI, MoneyMakerStats
)
from app.services.searxng_service import get_searxng_service

logger = structlog.get_logger()

# Default configuration for money maker service
_DEFAULT_CONFIG: Dict[str, Any] = {
    "user_profile": {
        "skills": ["python", "fastapi", "react", "llm", "automation"],
        "available_hours_per_week": 10,
        "capital_available": "low",
        "risk_tolerance": "medium"
    },
    "generation": {
        "ideas_per_cycle": 5,
        "categories": ["saas", "content", "freelance", "consulting", "affiliate", "product", "automation"]
    },
    "research": {
        "ideas_per_cycle": 3
    },
    "notifications": {
        "high_potential_threshold": 70,
        "discord_channel": "money-maker",
        "weekly_report_enabled": True
    }
}


def _orm_to_pydantic(row: MoneyIdeaModel) -> MoneyIdea:
    """Convert a MoneyIdeaModel ORM row to a MoneyIdea Pydantic model."""
    return MoneyIdea(
        id=row.id,
        title=row.title,
        description=row.description,
        category=row.category,
        status=row.status,
        revenue_potential=row.revenue_potential,
        effort_score=row.effort_score,
        time_to_roi=row.time_to_roi,
        market_validation=row.market_validation,
        competition_score=row.competition_score,
        skill_match=row.skill_match,
        viability_score=row.viability_score,
        research_notes=row.research_notes,
        market_size=row.market_size,
        competitors=row.competitors or [],
        resources_needed=row.resources_needed or [],
        first_steps=row.first_steps or [],
        source=row.source,
        rejection_reason=row.rejection_reason,
        park_reason=row.park_reason,
        linked_task_ids=row.linked_task_ids or [],
        generated_at=row.generated_at or datetime.now(timezone.utc),
        last_researched_at=row.last_researched_at,
        status_changed_at=row.status_changed_at,
    )


class MoneyMakerService:
    """
    Service for generating and managing money-making ideas.

    Uses LLM for idea generation and analysis, SearXNG for market research,
    and PostgreSQL for persistent storage.
    """

    def __init__(self):
        self.settings = get_settings()

    # ============================================
    # IDEA CRUD OPERATIONS
    # ============================================

    async def list_ideas(
        self,
        status: Optional[IdeaStatus] = None,
        category: Optional[IdeaCategory] = None,
        min_score: Optional[float] = None,
        limit: int = 50
    ) -> List[MoneyIdea]:
        """List ideas with optional filters, sorted by viability score."""
        async with get_session() as session:
            query = select(MoneyIdeaModel)

            if status:
                query = query.where(MoneyIdeaModel.status == status.value)
            if category:
                query = query.where(MoneyIdeaModel.category == category.value)
            if min_score is not None:
                query = query.where(MoneyIdeaModel.viability_score >= min_score)

            query = query.order_by(MoneyIdeaModel.viability_score.desc()).limit(limit)

            result = await session.execute(query)
            rows = result.scalars().all()
            return [_orm_to_pydantic(row) for row in rows]

    async def get_top_ideas(self, limit: int = 10) -> List[MoneyIdea]:
        """Get top ideas by viability score."""
        return await self.list_ideas(limit=limit)

    async def get_idea(self, idea_id: str) -> Optional[MoneyIdea]:
        """Get a specific idea by ID."""
        async with get_session() as session:
            row = await session.get(MoneyIdeaModel, idea_id)
            if row is None:
                return None
            return _orm_to_pydantic(row)

    async def create_idea(self, idea_data: MoneyIdeaCreate) -> MoneyIdea:
        """Create a new idea manually."""
        viability_score = self._calculate_viability_score(
            revenue_potential=idea_data.revenue_potential,
            effort_score=idea_data.effort_score,
            market_validation=50,
            competition_score=50,
            skill_match=50,
        )

        async with get_session() as session:
            # Generate next ID from current count
            result = await session.execute(
                select(func.count()).select_from(MoneyIdeaModel)
            )
            count = result.scalar() or 0
            idea_id = f"idea-{count + 1}"

            row = MoneyIdeaModel(
                id=idea_id,
                title=idea_data.title,
                description=idea_data.description,
                category=idea_data.category.value,
                status=IdeaStatus.NEW.value,
                revenue_potential=idea_data.revenue_potential,
                effort_score=idea_data.effort_score,
                time_to_roi=idea_data.time_to_roi.value,
                market_validation=50,
                competition_score=50,
                skill_match=50,
                viability_score=viability_score,
                first_steps=idea_data.first_steps,
                resources_needed=idea_data.resources_needed,
                competitors=[],
                source="manual",
                generated_at=datetime.now(timezone.utc),
            )
            session.add(row)
            # Flush to populate server defaults before converting
            await session.flush()

            logger.info("idea_created", idea_id=idea_id, title=idea_data.title)
            return _orm_to_pydantic(row)

    async def update_idea(
        self,
        idea_id: str,
        updates: MoneyIdeaUpdate
    ) -> Optional[MoneyIdea]:
        """Update an idea."""
        async with get_session() as session:
            row = await session.get(MoneyIdeaModel, idea_id)
            if row is None:
                return None

            update_dict = updates.model_dump(exclude_unset=True)
            for key, value in update_dict.items():
                if value is not None:
                    # Convert enums to their string values
                    if isinstance(value, (IdeaStatus, IdeaCategory, TimeToROI)):
                        value = value.value
                    setattr(row, key, value)

            # Recalculate viability score
            row.viability_score = self._calculate_viability_score(
                revenue_potential=row.revenue_potential,
                effort_score=row.effort_score,
                market_validation=row.market_validation,
                competition_score=row.competition_score,
                skill_match=row.skill_match,
            )

            await session.flush()
            logger.info("idea_updated", idea_id=idea_id)
            return _orm_to_pydantic(row)

    async def delete_idea(self, idea_id: str) -> bool:
        """Delete an idea."""
        async with get_session() as session:
            row = await session.get(MoneyIdeaModel, idea_id)
            if row is None:
                return False
            await session.delete(row)
            logger.info("idea_deleted", idea_id=idea_id)
            return True

    # ============================================
    # IDEA GENERATION
    # ============================================

    async def generate_ideas(
        self,
        count: int = 5,
        category: Optional[IdeaCategory] = None,
        focus_areas: Optional[List[str]] = None
    ) -> List[MoneyIdea]:
        """Generate new money-making ideas using LLM."""
        config = await self._get_config()
        user_profile = config.get("user_profile", {})

        # Build prompt
        skills = ", ".join(user_profile.get("skills", ["general"]))
        hours = user_profile.get("available_hours_per_week", 10)
        capital = user_profile.get("capital_available", "low")

        category_filter = ""
        if category:
            category_filter = f"\nFocus specifically on {category.value} ideas."
        elif focus_areas:
            category_filter = f"\nFocus on these areas: {', '.join(focus_areas)}"

        prompt = f"""Generate {count} realistic, actionable money-making ideas.

USER PROFILE:
- Skills: {skills}
- Available time: {hours} hours/week
- Capital available: {capital}
- Risk tolerance: {user_profile.get('risk_tolerance', 'medium')}
{category_filter}

For each idea, provide a JSON object with:
- title: Brief name (max 50 chars)
- description: 2-3 sentence explanation
- category: one of [saas, content, freelance, consulting, affiliate, product, automation, other]
- revenue_potential: estimated monthly revenue in dollars (be conservative)
- effort_score: 1-100 (1=very easy, 100=extremely difficult)
- time_to_roi: one of [immediate, short, medium, long, very_long]
- first_steps: list of 3 concrete first actions
- resources_needed: list of what's required to start

Output as a JSON array of ideas. Be realistic and specific."""

        ideas = []
        try:
            from app.infrastructure.ollama_client import get_ollama_client
            content = await get_ollama_client().chat_safe(
                prompt,
                task_type="analysis",
                system="You are a creative business consultant. Generate practical, actionable money-making ideas. Always respond with valid JSON array.",
                temperature=0.8,
                num_predict=2500,
                timeout=300,
            )

            if content:
                # Parse JSON from response
                try:
                    ideas_data = json.loads(content)
                except json.JSONDecodeError:
                    # Extract JSON array from markdown
                    json_match = re.search(r'\[[\s\S]*\]', content)
                    if json_match:
                        ideas_data = json.loads(json_match.group())
                    else:
                        ideas_data = []

                # Store generated ideas
                for idea_raw in ideas_data:
                    idea = await self._store_generated_idea(idea_raw)
                    if idea:
                        ideas.append(idea)

                logger.info("ideas_generated", count=len(ideas))

        except Exception as e:
            logger.error("idea_generation_failed", error=str(e))

        return ideas

    async def _store_generated_idea(self, idea_raw: Dict) -> Optional[MoneyIdea]:
        """Store a generated idea from LLM response."""
        # Normalize category
        category = idea_raw.get("category", "other").lower()
        if category not in [c.value for c in IdeaCategory]:
            category = "other"

        # Normalize time_to_roi
        time_to_roi = idea_raw.get("time_to_roi", "medium").lower()
        if time_to_roi not in [t.value for t in TimeToROI]:
            time_to_roi = "medium"

        # Calculate viability score
        revenue = float(idea_raw.get("revenue_potential", 0))
        effort = float(idea_raw.get("effort_score", 50))
        viability = self._calculate_viability_score(
            revenue_potential=revenue,
            effort_score=effort,
            market_validation=50,
            competition_score=50,
            skill_match=50
        )

        async with get_session() as session:
            # Generate next ID from current count
            result = await session.execute(
                select(func.count()).select_from(MoneyIdeaModel)
            )
            count = result.scalar() or 0
            idea_id = f"idea-{count + 1}"

            row = MoneyIdeaModel(
                id=idea_id,
                title=idea_raw.get("title", "Untitled Idea")[:500],
                description=idea_raw.get("description", ""),
                category=category,
                status=IdeaStatus.NEW.value,
                revenue_potential=revenue,
                effort_score=effort,
                time_to_roi=time_to_roi,
                market_validation=50,
                competition_score=50,
                skill_match=50,
                viability_score=viability,
                first_steps=idea_raw.get("first_steps", [])[:5],
                resources_needed=idea_raw.get("resources_needed", [])[:5],
                competitors=[],
                source="llm_generated",
                generated_at=datetime.now(timezone.utc),
            )
            session.add(row)
            await session.flush()

            return _orm_to_pydantic(row)

    # ============================================
    # IDEA RESEARCH
    # ============================================

    async def research_idea(self, idea_id: str) -> Optional[MoneyIdea]:
        """
        Research an idea using web search and LLM analysis.
        Updates market validation, competition score, and adds research notes.
        """
        idea = await self.get_idea(idea_id)
        if not idea:
            return None

        # Update status to researching
        await self.update_idea(idea_id, MoneyIdeaUpdate(status=IdeaStatus.RESEARCHING))

        # Perform web research
        searxng = get_searxng_service()
        research = await searxng.research_topic(
            idea.title,
            aspects=[
                "market size 2024",
                "competitors pricing",
                "how to start",
                "revenue examples",
                "challenges risks"
            ]
        )

        # Format research for LLM analysis
        research_text = searxng.format_research_for_llm(research)

        # Analyze with LLM
        analysis = await self._analyze_research_with_llm(idea, research_text)

        # Update idea with research results
        updates = MoneyIdeaUpdate(
            status=IdeaStatus.VALIDATED,
            market_validation=analysis.get("market_validation", 50),
            competition_score=analysis.get("competition_score", 50),
            research_notes=analysis.get("research_notes", ""),
            market_size=analysis.get("market_size", ""),
            competitors=analysis.get("competitors", [])
        )

        if analysis.get("revenue_potential"):
            updates.revenue_potential = analysis["revenue_potential"]

        await self.update_idea(idea_id, updates)

        # Update last_researched_at timestamp directly
        async with get_session() as session:
            row = await session.get(MoneyIdeaModel, idea_id)
            if row:
                row.last_researched_at = datetime.now(timezone.utc)
                await session.flush()

        logger.info("idea_researched", idea_id=idea_id)
        return await self.get_idea(idea_id)

    async def _analyze_research_with_llm(
        self,
        idea: MoneyIdea,
        research_text: str
    ) -> Dict[str, Any]:
        """Analyze research results with LLM."""
        prompt = f"""Analyze this business idea based on web research:

IDEA: {idea.title}
DESCRIPTION: {idea.description}

WEB RESEARCH RESULTS:
{research_text[:4000]}

Based on this research, provide a JSON analysis with:
- market_validation: 0-100 score (how validated is market demand?)
- competition_score: 0-100 score (how competitive? 0=blue ocean, 100=saturated)
- revenue_potential: updated monthly revenue estimate in dollars
- market_size: brief market size description
- competitors: list of main competitors found (max 5)
- research_notes: 2-3 key insights from the research

Be realistic and data-driven in your analysis."""

        try:
            from app.infrastructure.ollama_client import get_ollama_client
            content = await get_ollama_client().chat_safe(
                prompt,
                task_type="research",
                system="You are a business analyst. Analyze market research and provide realistic assessments. Always respond with valid JSON.",
                temperature=0.3,
                num_predict=1000,
                timeout=300,
            )

            if content:
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    json_match = re.search(r'\{[\s\S]*\}', content)
                    if json_match:
                        return json.loads(json_match.group())

        except Exception as e:
            logger.warning("research_analysis_failed", error=str(e))

        return {
            "market_validation": 50,
            "competition_score": 50,
            "research_notes": "Research analysis unavailable"
        }

    # ============================================
    # IDEA ACTIONS
    # ============================================

    async def pursue_idea(
        self,
        idea_id: str,
        action: MoneyIdeaAction
    ) -> Dict[str, Any]:
        """
        Mark idea as pursuing and optionally create sprint tasks.
        """
        idea = await self.get_idea(idea_id)
        if not idea:
            return {"success": False, "error": "Idea not found"}

        # Update status and timestamp
        async with get_session() as session:
            row = await session.get(MoneyIdeaModel, idea_id)
            if row:
                row.status = IdeaStatus.PURSUING.value
                row.status_changed_at = datetime.now(timezone.utc)
                await session.flush()

        result = {
            "success": True,
            "idea_id": idea_id,
            "status": IdeaStatus.PURSUING.value,
            "tasks_created": []
        }

        # Create tasks if sprint_id provided
        if action.sprint_id and idea.first_steps:
            try:
                from app.services.task_service import get_task_service
                from app.models.task import TaskCreate, TaskCategory, TaskPriority

                task_service = get_task_service()
                created_task_ids = []

                for step in idea.first_steps[:5]:
                    task_data = TaskCreate(
                        title=f"[Money Maker] {step}",
                        description=f"From idea: {idea.title}\n\n{idea.description or ''}",
                        sprint_id=action.sprint_id,
                        category=TaskCategory.FEATURE,
                        priority=TaskPriority.MEDIUM
                    )
                    task = await task_service.create_task(task_data)
                    created_task_ids.append(task.id)

                result["tasks_created"] = created_task_ids

                # Link tasks to idea
                async with get_session() as session:
                    row = await session.get(MoneyIdeaModel, idea_id)
                    if row:
                        row.linked_task_ids = created_task_ids
                        await session.flush()

            except Exception as e:
                logger.warning("task_creation_failed", error=str(e))

        logger.info("idea_pursued", idea_id=idea_id, tasks=len(result["tasks_created"]))
        return result

    async def park_idea(self, idea_id: str, action: MoneyIdeaAction) -> Optional[MoneyIdea]:
        """Park an idea for later consideration."""
        async with get_session() as session:
            row = await session.get(MoneyIdeaModel, idea_id)
            if row is None:
                return None

            row.status = IdeaStatus.PARKED.value
            row.park_reason = action.reason
            row.status_changed_at = datetime.now(timezone.utc)
            await session.flush()

            logger.info("idea_parked", idea_id=idea_id)
            return _orm_to_pydantic(row)

    async def reject_idea(self, idea_id: str, action: MoneyIdeaAction) -> Optional[MoneyIdea]:
        """Reject an idea with reason."""
        async with get_session() as session:
            row = await session.get(MoneyIdeaModel, idea_id)
            if row is None:
                return None

            row.status = IdeaStatus.REJECTED.value
            row.rejection_reason = action.reason
            row.status_changed_at = datetime.now(timezone.utc)
            await session.flush()

            logger.info("idea_rejected", idea_id=idea_id)
            return _orm_to_pydantic(row)

    # ============================================
    # AUTONOMOUS CYCLE
    # ============================================

    async def run_daily_cycle(self) -> Dict[str, Any]:
        """
        Run the full autonomous daily cycle:
        1. Generate new ideas
        2. Research top unresearched ideas
        3. Rank all ideas
        4. Return high-potential opportunities
        """
        logger.info("money_maker_cycle_starting")

        config = await self._get_config()
        gen_config = config.get("generation", {})
        research_config = config.get("research", {})
        notify_config = config.get("notifications", {})

        result = {
            "generated": 0,
            "researched": 0,
            "high_potential": [],
            "top_ideas": []
        }

        # 1. Generate new ideas
        ideas_per_cycle = gen_config.get("ideas_per_cycle", 5)
        new_ideas = await self.generate_ideas(count=ideas_per_cycle)
        result["generated"] = len(new_ideas)

        # 2. Research top unresearched ideas
        research_per_cycle = research_config.get("ideas_per_cycle", 3)
        unresearched = await self.list_ideas(status=IdeaStatus.NEW, limit=research_per_cycle)

        for idea in unresearched:
            await self.research_idea(idea.id)
            result["researched"] += 1
            await asyncio.sleep(1)  # Rate limiting

        # 3. Get ranked ideas
        top_ideas = await self.get_top_ideas(limit=10)
        result["top_ideas"] = [
            {"id": i.id, "title": i.title, "viability_score": i.viability_score}
            for i in top_ideas
        ]

        # 4. Identify high-potential ideas
        threshold = notify_config.get("high_potential_threshold", 70)
        result["high_potential"] = [
            {"id": i.id, "title": i.title, "viability_score": i.viability_score}
            for i in top_ideas if i.viability_score >= threshold
        ]

        # 5. Send notification if high-potential ideas found
        if result["high_potential"]:
            await self._send_notification(result)

        logger.info(
            "money_maker_cycle_complete",
            generated=result["generated"],
            researched=result["researched"],
            high_potential=len(result["high_potential"])
        )

        return result

    async def _send_notification(self, cycle_result: Dict[str, Any]):
        """Send notification about high-potential ideas."""
        try:
            from app.services.notification_service import get_notification_service

            message_lines = ["**Money Maker Alert**\n"]
            message_lines.append(f"Found {len(cycle_result['high_potential'])} high-potential opportunities!\n")

            for idea in cycle_result["high_potential"][:5]:
                message_lines.append(f"- **{idea['title']}** (Score: {idea['viability_score']:.1f})")

            message_lines.append(f"\n_{cycle_result['generated']} new ideas, {cycle_result['researched']} researched_")

            notification_service = get_notification_service()
            await notification_service.create_notification(
                title="Money Maker Opportunities",
                message="\n".join(message_lines),
                channel="discord",
                source="money_maker"
            )

        except Exception as e:
            logger.warning("notification_failed", error=str(e))

    # ============================================
    # STATISTICS
    # ============================================

    async def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the idea pipeline."""
        async with get_session() as session:
            # Total count
            total_result = await session.execute(
                select(func.count()).select_from(MoneyIdeaModel)
            )
            total = total_result.scalar() or 0

            if total == 0:
                return {
                    "total_ideas": 0,
                    "by_status": {},
                    "by_category": {},
                    "top_viability_score": 0,
                    "avg_viability_score": 0,
                    "ideas_this_week": 0,
                    "researched_this_week": 0
                }

            # Count by status
            status_result = await session.execute(
                select(
                    MoneyIdeaModel.status,
                    func.count()
                ).group_by(MoneyIdeaModel.status)
            )
            by_status = {row[0]: row[1] for row in status_result.all()}

            # Count by category
            category_result = await session.execute(
                select(
                    MoneyIdeaModel.category,
                    func.count()
                ).group_by(MoneyIdeaModel.category)
            )
            by_category = {row[0]: row[1] for row in category_result.all()}

            # Viability score aggregates
            score_result = await session.execute(
                select(
                    func.max(MoneyIdeaModel.viability_score),
                    func.avg(MoneyIdeaModel.viability_score),
                )
            )
            score_row = score_result.one()
            top_score = score_row[0] or 0
            avg_score = float(score_row[1] or 0)

            # Ideas generated this week
            week_ago = datetime.now(timezone.utc) - timedelta(days=7)
            week_ideas_result = await session.execute(
                select(func.count()).select_from(MoneyIdeaModel).where(
                    MoneyIdeaModel.generated_at >= week_ago
                )
            )
            ideas_this_week = week_ideas_result.scalar() or 0

            # Ideas researched this week
            week_researched_result = await session.execute(
                select(func.count()).select_from(MoneyIdeaModel).where(
                    MoneyIdeaModel.last_researched_at >= week_ago
                )
            )
            researched_this_week = week_researched_result.scalar() or 0

            return {
                "total_ideas": total,
                "by_status": by_status,
                "by_category": by_category,
                "top_viability_score": top_score,
                "avg_viability_score": round(avg_score, 2),
                "ideas_this_week": ideas_this_week,
                "researched_this_week": researched_this_week
            }

    # ============================================
    # UTILITIES
    # ============================================

    def _calculate_viability_score(
        self,
        revenue_potential: float,
        effort_score: float,
        market_validation: float,
        competition_score: float,
        skill_match: float
    ) -> float:
        """
        Calculate viability score using weighted formula.

        Weights:
        - Revenue potential: 30%
        - Low effort: 20%
        - Market validation: 25%
        - Low competition: 15%
        - Skill match: 10%
        """
        # Normalize revenue to 0-100 scale (assuming max $10k/month is 100)
        revenue_normalized = min(100, (revenue_potential / 10000) * 100)

        score = (
            revenue_normalized * 0.30 +
            (100 - effort_score) * 0.20 +
            market_validation * 0.25 +
            (100 - competition_score) * 0.15 +
            skill_match * 0.10
        )

        return round(min(100, max(0, score)), 2)

    async def _get_config(self) -> Dict[str, Any]:
        """Get money maker configuration from service_configs table."""
        async with get_session() as session:
            row = await session.get(ServiceConfigModel, "money_maker")

            if row is None:
                # Insert default config
                row = ServiceConfigModel(
                    service_name="money_maker",
                    config=_DEFAULT_CONFIG,
                )
                session.add(row)
                await session.flush()
                return _DEFAULT_CONFIG

            return row.config


@lru_cache()
def get_money_maker_service() -> MoneyMakerService:
    """Get cached money maker service instance."""
    return MoneyMakerService()
