"""
Money Maker Service.
Generates, researches, ranks, and tracks money-making ideas using LLM + web research.
"""

import asyncio
import json
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from functools import lru_cache
import structlog
import httpx

from app.infrastructure.storage import JsonStorage
from app.infrastructure.config import get_settings, get_workspace_path
from app.models.money_maker import (
    MoneyIdea, MoneyIdeaCreate, MoneyIdeaUpdate, MoneyIdeaAction,
    IdeaStatus, IdeaCategory, TimeToROI, MoneyMakerStats
)
from app.services.searxng_service import get_searxng_service

logger = structlog.get_logger()


def get_money_maker_path():
    """Get path to money-maker data directory."""
    return get_workspace_path("money-maker")


class MoneyMakerService:
    """
    Service for generating and managing money-making ideas.

    Uses LLM for idea generation and analysis, SearXNG for market research,
    and maintains an isolated task list for tracking opportunities.
    """

    def __init__(self):
        self.storage = JsonStorage(get_money_maker_path())
        self.settings = get_settings()
        self._ideas_file = "ideas.json"
        self._config_file = "config.json"

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
        data = await self.storage.read(self._ideas_file)
        ideas = data.get("ideas", [])

        # Apply filters
        filtered = []
        for idea_data in ideas:
            if status and idea_data.get("status") != status.value:
                continue
            if category and idea_data.get("category") != category.value:
                continue
            if min_score and idea_data.get("viabilityScore", 0) < min_score:
                continue
            filtered.append(self._normalize_idea_data(idea_data))

        # Sort by viability score descending
        filtered.sort(key=lambda x: x.get("viability_score", 0), reverse=True)

        # Convert to models
        return [MoneyIdea(**idea) for idea in filtered[:limit]]

    async def get_top_ideas(self, limit: int = 10) -> List[MoneyIdea]:
        """Get top ideas by viability score."""
        return await self.list_ideas(limit=limit)

    async def get_idea(self, idea_id: str) -> Optional[MoneyIdea]:
        """Get a specific idea by ID."""
        data = await self.storage.read(self._ideas_file)
        for idea_data in data.get("ideas", []):
            if idea_data.get("id") == idea_id:
                return MoneyIdea(**self._normalize_idea_data(idea_data))
        return None

    async def create_idea(self, idea_data: MoneyIdeaCreate) -> MoneyIdea:
        """Create a new idea manually."""
        data = await self.storage.read(self._ideas_file)

        if "ideas" not in data:
            data["ideas"] = []
            data["nextIdeaId"] = 1

        # Generate ID
        idea_id = f"idea-{data.get('nextIdeaId', 1)}"
        data["nextIdeaId"] = data.get("nextIdeaId", 1) + 1

        # Calculate viability score
        viability_score = self._calculate_viability_score(
            revenue_potential=idea_data.revenue_potential,
            effort_score=idea_data.effort_score,
            market_validation=50,  # Default
            competition_score=50,  # Default
            skill_match=50  # Default
        )

        # Create idea dict
        idea = {
            "id": idea_id,
            "title": idea_data.title,
            "description": idea_data.description,
            "category": idea_data.category.value,
            "status": IdeaStatus.NEW.value,
            "revenuePotential": idea_data.revenue_potential,
            "effortScore": idea_data.effort_score,
            "timeToRoi": idea_data.time_to_roi.value,
            "marketValidation": 50,
            "competitionScore": 50,
            "skillMatch": 50,
            "viabilityScore": viability_score,
            "firstSteps": idea_data.first_steps,
            "resourcesNeeded": idea_data.resources_needed,
            "competitors": [],
            "source": "manual",
            "generatedAt": datetime.utcnow().isoformat(),
        }

        data["ideas"].append(idea)
        await self.storage.write(self._ideas_file, data)

        logger.info("idea_created", idea_id=idea_id, title=idea_data.title)
        return MoneyIdea(**self._normalize_idea_data(idea))

    async def update_idea(
        self,
        idea_id: str,
        updates: MoneyIdeaUpdate
    ) -> Optional[MoneyIdea]:
        """Update an idea."""
        data = await self.storage.read(self._ideas_file)

        for i, idea in enumerate(data.get("ideas", [])):
            if idea.get("id") == idea_id:
                # Apply updates
                update_dict = updates.model_dump(exclude_unset=True)
                for key, value in update_dict.items():
                    if value is not None:
                        storage_key = self._to_camel_case(key)
                        if isinstance(value, IdeaStatus):
                            idea[storage_key] = value.value
                        elif isinstance(value, IdeaCategory):
                            idea[storage_key] = value.value
                        elif isinstance(value, TimeToROI):
                            idea[storage_key] = value.value
                        else:
                            idea[storage_key] = value

                # Recalculate viability score
                idea["viabilityScore"] = self._calculate_viability_score(
                    revenue_potential=idea.get("revenuePotential", 0),
                    effort_score=idea.get("effortScore", 50),
                    market_validation=idea.get("marketValidation", 50),
                    competition_score=idea.get("competitionScore", 50),
                    skill_match=idea.get("skillMatch", 50)
                )

                data["ideas"][i] = idea
                await self.storage.write(self._ideas_file, data)

                logger.info("idea_updated", idea_id=idea_id)
                return MoneyIdea(**self._normalize_idea_data(idea))

        return None

    async def delete_idea(self, idea_id: str) -> bool:
        """Delete an idea."""
        data = await self.storage.read(self._ideas_file)
        original_count = len(data.get("ideas", []))
        data["ideas"] = [i for i in data.get("ideas", []) if i.get("id") != idea_id]

        if len(data["ideas"]) < original_count:
            await self.storage.write(self._ideas_file, data)
            logger.info("idea_deleted", idea_id=idea_id)
            return True
        return False

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
            async with httpx.AsyncClient(timeout=90.0) as client:
                response = await client.post(
                    f"{self.settings.ollama_base_url}/chat/completions",
                    json={
                        "model": self.settings.ollama_model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "You are a creative business consultant. Generate practical, actionable money-making ideas. Always respond with valid JSON array."
                            },
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.8,
                        "max_tokens": 2500
                    }
                )

                if response.status_code == 200:
                    result = response.json()
                    content = result.get("choices", [{}])[0].get("message", {}).get("content", "[]")

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
        data = await self.storage.read(self._ideas_file)

        if "ideas" not in data:
            data["ideas"] = []
            data["nextIdeaId"] = 1

        idea_id = f"idea-{data.get('nextIdeaId', 1)}"
        data["nextIdeaId"] = data.get("nextIdeaId", 1) + 1

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

        idea = {
            "id": idea_id,
            "title": idea_raw.get("title", "Untitled Idea")[:500],
            "description": idea_raw.get("description", ""),
            "category": category,
            "status": IdeaStatus.NEW.value,
            "revenuePotential": revenue,
            "effortScore": effort,
            "timeToRoi": time_to_roi,
            "marketValidation": 50,
            "competitionScore": 50,
            "skillMatch": 50,
            "viabilityScore": viability,
            "firstSteps": idea_raw.get("first_steps", [])[:5],
            "resourcesNeeded": idea_raw.get("resources_needed", [])[:5],
            "competitors": [],
            "source": "llm_generated",
            "generatedAt": datetime.utcnow().isoformat(),
        }

        data["ideas"].append(idea)
        await self.storage.write(self._ideas_file, data)

        return MoneyIdea(**self._normalize_idea_data(idea))

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

        updated_idea = await self.update_idea(idea_id, updates)

        # Update last researched timestamp
        data = await self.storage.read(self._ideas_file)
        for i, stored_idea in enumerate(data.get("ideas", [])):
            if stored_idea.get("id") == idea_id:
                stored_idea["lastResearchedAt"] = datetime.utcnow().isoformat()
                data["ideas"][i] = stored_idea
                await self.storage.write(self._ideas_file, data)
                break

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
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.settings.ollama_base_url}/chat/completions",
                    json={
                        "model": self.settings.ollama_model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "You are a business analyst. Analyze market research and provide realistic assessments. Always respond with valid JSON."
                            },
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.3,
                        "max_tokens": 1000
                    }
                )

                if response.status_code == 200:
                    result = response.json()
                    content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")

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

        # Update status
        await self.update_idea(idea_id, MoneyIdeaUpdate(status=IdeaStatus.PURSUING))

        # Update status changed timestamp
        data = await self.storage.read(self._ideas_file)
        for i, stored_idea in enumerate(data.get("ideas", [])):
            if stored_idea.get("id") == idea_id:
                stored_idea["statusChangedAt"] = datetime.utcnow().isoformat()
                data["ideas"][i] = stored_idea
                await self.storage.write(self._ideas_file, data)
                break

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
                for stored_idea in data.get("ideas", []):
                    if stored_idea.get("id") == idea_id:
                        stored_idea["linkedTaskIds"] = created_task_ids
                        await self.storage.write(self._ideas_file, data)
                        break

            except Exception as e:
                logger.warning("task_creation_failed", error=str(e))

        logger.info("idea_pursued", idea_id=idea_id, tasks=len(result["tasks_created"]))
        return result

    async def park_idea(self, idea_id: str, action: MoneyIdeaAction) -> Optional[MoneyIdea]:
        """Park an idea for later consideration."""
        data = await self.storage.read(self._ideas_file)

        for i, idea in enumerate(data.get("ideas", [])):
            if idea.get("id") == idea_id:
                idea["status"] = IdeaStatus.PARKED.value
                idea["parkReason"] = action.reason
                idea["statusChangedAt"] = datetime.utcnow().isoformat()
                data["ideas"][i] = idea
                await self.storage.write(self._ideas_file, data)

                logger.info("idea_parked", idea_id=idea_id)
                return MoneyIdea(**self._normalize_idea_data(idea))

        return None

    async def reject_idea(self, idea_id: str, action: MoneyIdeaAction) -> Optional[MoneyIdea]:
        """Reject an idea with reason."""
        data = await self.storage.read(self._ideas_file)

        for i, idea in enumerate(data.get("ideas", [])):
            if idea.get("id") == idea_id:
                idea["status"] = IdeaStatus.REJECTED.value
                idea["rejectionReason"] = action.reason
                idea["statusChangedAt"] = datetime.utcnow().isoformat()
                data["ideas"][i] = idea
                await self.storage.write(self._ideas_file, data)

                logger.info("idea_rejected", idea_id=idea_id)
                return MoneyIdea(**self._normalize_idea_data(idea))

        return None

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
        data = await self.storage.read(self._ideas_file)
        ideas = data.get("ideas", [])

        if not ideas:
            return {
                "totalIdeas": 0,
                "byStatus": {},
                "byCategory": {},
                "topViabilityScore": 0,
                "avgViabilityScore": 0,
                "ideasThisWeek": 0,
                "researchedThisWeek": 0
            }

        # Count by status and category
        by_status = {}
        by_category = {}
        viability_scores = []
        week_ago = datetime.utcnow() - timedelta(days=7)
        ideas_this_week = 0
        researched_this_week = 0

        for idea in ideas:
            status = idea.get("status", "new")
            category = idea.get("category", "other")

            by_status[status] = by_status.get(status, 0) + 1
            by_category[category] = by_category.get(category, 0) + 1

            score = idea.get("viabilityScore", 0)
            viability_scores.append(score)

            # Check if generated this week
            generated_at = idea.get("generatedAt")
            if generated_at:
                try:
                    gen_date = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
                    if gen_date.replace(tzinfo=None) > week_ago:
                        ideas_this_week += 1
                except (ValueError, AttributeError):
                    pass

            # Check if researched this week
            researched_at = idea.get("lastResearchedAt")
            if researched_at:
                try:
                    res_date = datetime.fromisoformat(researched_at.replace("Z", "+00:00"))
                    if res_date.replace(tzinfo=None) > week_ago:
                        researched_this_week += 1
                except (ValueError, AttributeError):
                    pass

        return {
            "totalIdeas": len(ideas),
            "byStatus": by_status,
            "byCategory": by_category,
            "topViabilityScore": max(viability_scores) if viability_scores else 0,
            "avgViabilityScore": sum(viability_scores) / len(viability_scores) if viability_scores else 0,
            "ideasThisWeek": ideas_this_week,
            "researchedThisWeek": researched_this_week
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

    def _normalize_idea_data(self, idea_data: Dict) -> Dict:
        """Convert camelCase storage format to snake_case for Pydantic."""
        return {
            "id": idea_data.get("id"),
            "title": idea_data.get("title"),
            "description": idea_data.get("description"),
            "category": idea_data.get("category", "other"),
            "status": idea_data.get("status", "new"),
            "revenue_potential": idea_data.get("revenuePotential", 0),
            "effort_score": idea_data.get("effortScore", 50),
            "time_to_roi": idea_data.get("timeToRoi", "medium"),
            "market_validation": idea_data.get("marketValidation", 50),
            "competition_score": idea_data.get("competitionScore", 50),
            "skill_match": idea_data.get("skillMatch", 50),
            "viability_score": idea_data.get("viabilityScore", 0),
            "research_notes": idea_data.get("researchNotes"),
            "market_size": idea_data.get("marketSize"),
            "competitors": idea_data.get("competitors", []),
            "resources_needed": idea_data.get("resourcesNeeded", []),
            "first_steps": idea_data.get("firstSteps", []),
            "source": idea_data.get("source", "manual"),
            "rejection_reason": idea_data.get("rejectionReason"),
            "park_reason": idea_data.get("parkReason"),
            "linked_task_ids": idea_data.get("linkedTaskIds", []),
            "generated_at": idea_data.get("generatedAt", datetime.utcnow().isoformat()),
            "last_researched_at": idea_data.get("lastResearchedAt"),
            "status_changed_at": idea_data.get("statusChangedAt"),
        }

    def _to_camel_case(self, snake_str: str) -> str:
        """Convert snake_case to camelCase."""
        components = snake_str.split('_')
        return components[0] + ''.join(x.title() for x in components[1:])

    async def _get_config(self) -> Dict[str, Any]:
        """Get money maker configuration."""
        config = await self.storage.read(self._config_file)

        # Return defaults if config doesn't exist
        if not config:
            config = {
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
            await self.storage.write(self._config_file, config)

        return config


@lru_cache()
def get_money_maker_service() -> MoneyMakerService:
    """Get cached money maker service instance."""
    return MoneyMakerService()
