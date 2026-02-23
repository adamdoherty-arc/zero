"""
Research Rules Engine Service.
Dynamic rules for scoring, categorization, routing, and auto-actions on research findings.
Supports auto-learning: tracks effectiveness and auto-adjusts rules based on feedback.
"""

import uuid
from datetime import datetime, time as dt_time
from typing import List, Dict, Any, Optional
from functools import lru_cache
import structlog

from sqlalchemy import select, update, func as sql_func

from app.infrastructure.database import get_session
from app.db.models import ResearchRuleModel, ResearchFindingModel
from app.models.research_rules import (
    ResearchRule, ResearchRuleCreate, ResearchRuleUpdate,
    RuleType, RuleCondition, RuleAction,
    RuleEvaluationResult, RuleStats, RuleSuggestion,
)

logger = structlog.get_logger()


# ============================================================================
# Default Rules (seeded on startup)
# ============================================================================

DEFAULT_RULES = [
    {
        "name": "GitHub repos boost actionability",
        "description": "GitHub repository URLs are highly actionable — boost score and tag as open-source",
        "rule_type": "scoring",
        "conditions": {"url_domain": ["github.com"]},
        "actions": {"boost_actionability": 15, "set_category": "repo", "add_tags": ["open-source"]},
        "priority": 10,
        "created_by": "system",
    },
    {
        "name": "ArXiv papers → research category",
        "description": "ArXiv papers are academic research — tag and categorize appropriately",
        "rule_type": "categorization",
        "conditions": {"url_domain": ["arxiv.org"]},
        "actions": {"set_category": "article", "add_tags": ["research", "paper"], "set_category_id": "ai-research"},
        "priority": 10,
        "created_by": "system",
    },
    {
        "name": "Trading/finance → trading category",
        "description": "Options, CSP, and trading keywords route to the trading knowledge category",
        "rule_type": "categorization",
        "conditions": {
            "operator": "or",
            "title_contains": ["options", "CSP", "covered call", "wheel strategy", "put selling", "premium", "theta", "delta", "strike price"],
        },
        "actions": {"set_category_id": "trading/options", "add_tags": ["trading"]},
        "priority": 20,
        "created_by": "system",
    },
    {
        "name": "LangGraph/LangChain → agents category",
        "description": "LangGraph and LangChain content routes to AI agents research",
        "rule_type": "categorization",
        "conditions": {
            "operator": "or",
            "title_contains": ["langgraph", "langchain", "langsmith"],
            "snippet_contains": ["langgraph", "langchain"],
        },
        "actions": {"set_category_id": "ai-research/agents", "add_tags": ["langgraph", "langchain"]},
        "priority": 15,
        "created_by": "system",
    },
    {
        "name": "MCP servers → tools category",
        "description": "MCP server and tool-use content routes to tools research",
        "rule_type": "categorization",
        "conditions": {
            "operator": "or",
            "title_contains": ["mcp server", "model context protocol", "tool use"],
            "snippet_contains": ["mcp server", "model context protocol"],
        },
        "actions": {"set_category_id": "ai-research/tools-mcp", "add_tags": ["mcp", "tools"]},
        "priority": 15,
        "created_by": "system",
    },
    {
        "name": "High-value findings auto-notify",
        "description": "Findings with composite score >= 80 get Discord notification",
        "rule_type": "auto_action",
        "conditions": {"min_composite_score": 80},
        "actions": {"notify_discord": True, "priority_label": "high"},
        "priority": 50,
        "created_by": "system",
    },
    {
        "name": "Auto-dismiss spam/ads",
        "description": "Auto-dismiss results that look like sponsored content or advertisements",
        "rule_type": "auto_action",
        "conditions": {
            "snippet_contains": ["sponsored", "advertisement", "buy now", "limited time offer", "click here to buy"],
        },
        "actions": {"auto_dismiss": True},
        "priority": 5,
        "created_by": "system",
    },
    {
        "name": "Ollama/local LLM → models category",
        "description": "Ollama and local LLM content routes to models research",
        "rule_type": "categorization",
        "conditions": {
            "operator": "or",
            "title_contains": ["ollama", "local llm", "gguf", "llama.cpp", "vllm"],
            "snippet_contains": ["ollama", "local llm"],
        },
        "actions": {"set_category_id": "ai-research/models-llms", "add_tags": ["ollama", "local-llm"]},
        "priority": 15,
        "created_by": "system",
    },
]


def _generate_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class ResearchRulesService:
    """Dynamic rules engine for research findings."""

    # ==================================================================
    # Rule CRUD
    # ==================================================================

    async def create_rule(self, data: ResearchRuleCreate) -> ResearchRule:
        """Create a new research rule."""
        rule_id = _generate_id("rule")

        async with get_session() as session:
            row = ResearchRuleModel(
                id=rule_id,
                name=data.name,
                description=data.description,
                rule_type=data.rule_type.value,
                conditions=data.conditions.model_dump(exclude_none=True),
                actions=data.actions.model_dump(exclude_none=True),
                priority=data.priority,
                enabled=data.enabled,
                category_id=data.category_id,
                created_by="user",
            )
            session.add(row)
            await session.flush()

        logger.info("Research rule created", rule_id=rule_id, name=data.name)
        return await self.get_rule(rule_id)

    async def list_rules(
        self,
        rule_type: Optional[RuleType] = None,
        enabled: Optional[bool] = None,
        category_id: Optional[str] = None,
    ) -> List[ResearchRule]:
        """List rules with optional filters."""
        async with get_session() as session:
            query = select(ResearchRuleModel).order_by(ResearchRuleModel.priority)

            if rule_type:
                query = query.where(ResearchRuleModel.rule_type == rule_type.value)
            if enabled is not None:
                query = query.where(ResearchRuleModel.enabled == enabled)
            if category_id:
                query = query.where(ResearchRuleModel.category_id == category_id)

            result = await session.execute(query)
            rows = result.scalars().all()
            return [self._orm_to_rule(row) for row in rows]

    async def get_rule(self, rule_id: str) -> Optional[ResearchRule]:
        """Get a single rule by ID."""
        async with get_session() as session:
            row = await session.get(ResearchRuleModel, rule_id)
            if row is None:
                return None
            return self._orm_to_rule(row)

    async def update_rule(self, rule_id: str, data: ResearchRuleUpdate) -> Optional[ResearchRule]:
        """Update a research rule."""
        async with get_session() as session:
            row = await session.get(ResearchRuleModel, rule_id)
            if row is None:
                return None

            update_dict = data.model_dump(exclude_unset=True)
            for key, value in update_dict.items():
                if value is not None:
                    if key == "conditions":
                        value = value.model_dump(exclude_none=True) if hasattr(value, 'model_dump') else value
                    elif key == "actions":
                        value = value.model_dump(exclude_none=True) if hasattr(value, 'model_dump') else value
                    elif key == "rule_type" and hasattr(value, 'value'):
                        value = value.value
                    setattr(row, key, value)

            row.updated_at = datetime.utcnow()
            await session.flush()

        logger.info("Research rule updated", rule_id=rule_id)
        return await self.get_rule(rule_id)

    async def delete_rule(self, rule_id: str) -> bool:
        """Delete a research rule."""
        async with get_session() as session:
            row = await session.get(ResearchRuleModel, rule_id)
            if row is None:
                return False
            await session.delete(row)

        logger.info("Research rule deleted", rule_id=rule_id)
        return True

    async def toggle_rule(self, rule_id: str) -> Optional[ResearchRule]:
        """Toggle a rule's enabled state."""
        async with get_session() as session:
            row = await session.get(ResearchRuleModel, rule_id)
            if row is None:
                return None
            row.enabled = not row.enabled
            row.updated_at = datetime.utcnow()
            await session.flush()

        logger.info("Research rule toggled", rule_id=rule_id, enabled=not row.enabled)
        return await self.get_rule(rule_id)

    # ==================================================================
    # Rule Evaluation Engine
    # ==================================================================

    async def evaluate_rules(self, finding: Dict, context: Optional[Dict] = None) -> RuleEvaluationResult:
        """Evaluate all enabled rules against a finding, return merged actions."""
        rules = await self.list_rules(enabled=True)
        result = RuleEvaluationResult(rules_evaluated=len(rules))

        matched_actions: List[RuleAction] = []

        for rule in rules:
            if self._evaluate_condition(rule.conditions, finding, context or {}):
                result.matched_rule_ids.append(rule.id)
                matched_actions.append(rule.actions)

                # Increment fire count
                await self._increment_fire_count(rule.id)

        result.rules_matched = len(result.matched_rule_ids)

        if matched_actions:
            result.merged_actions = self._merge_actions(matched_actions)

        return result

    def _evaluate_condition(self, condition: RuleCondition, finding: Dict, context: Dict) -> bool:
        """Recursively evaluate a condition tree against a finding."""
        results = []

        title = finding.get("title", "").lower()
        snippet = finding.get("snippet", "").lower()
        url = finding.get("url", "").lower()
        text = f"{title} {snippet}".replace("-", " ")

        # Text matching conditions
        if condition.title_contains:
            results.append(any(kw.lower() in title for kw in condition.title_contains))

        if condition.snippet_contains:
            results.append(any(kw.lower() in snippet for kw in condition.snippet_contains))

        if condition.url_contains:
            results.append(any(kw.lower() in url for kw in condition.url_contains))

        if condition.url_domain:
            results.append(any(domain.lower() in url for domain in condition.url_domain))

        # Score threshold conditions
        if condition.min_composite_score is not None:
            score = finding.get("compositeScore", finding.get("composite_score", 0))
            results.append(score >= condition.min_composite_score)

        if condition.max_composite_score is not None:
            score = finding.get("compositeScore", finding.get("composite_score", 0))
            results.append(score <= condition.max_composite_score)

        if condition.min_relevance_score is not None:
            score = finding.get("relevanceScore", finding.get("relevance_score", 0))
            results.append(score >= condition.min_relevance_score)

        # Context conditions
        if condition.category_is:
            cat = finding.get("category", "other")
            results.append(cat in condition.category_is)

        if condition.topic_tags_include:
            tags = finding.get("tags", [])
            results.append(any(t in tags for t in condition.topic_tags_include))

        if condition.source_engine:
            engine = finding.get("sourceEngine", finding.get("source_engine", ""))
            results.append(engine in condition.source_engine)

        # Time-based conditions
        if condition.time_of_day:
            now = datetime.utcnow().time()
            after = condition.time_of_day.get("after")
            before = condition.time_of_day.get("before")
            time_match = True
            if after:
                h, m = map(int, after.split(":"))
                time_match = time_match and now >= dt_time(h, m)
            if before:
                h, m = map(int, before.split(":"))
                time_match = time_match and now <= dt_time(h, m)
            results.append(time_match)

        if condition.day_of_week:
            results.append(datetime.utcnow().weekday() in condition.day_of_week)

        # Nested sub-conditions
        if condition.conditions:
            for sub in condition.conditions:
                results.append(self._evaluate_condition(sub, finding, context))

        # If no conditions matched, rule doesn't fire
        if not results:
            return False

        # Combine results based on operator
        if condition.operator == "or":
            return any(results)
        else:  # "and"
            return all(results)

    def _merge_actions(self, actions: List[RuleAction]) -> RuleAction:
        """Merge multiple rule actions. Later rules can override earlier ones.
        Score boosts are cumulative; other fields use last-wins."""
        merged = RuleAction()
        total_boost_rel = 0.0
        total_boost_nov = 0.0
        total_boost_act = 0.0
        all_tags: List[str] = []

        for action in actions:
            if action.boost_relevance is not None:
                total_boost_rel += action.boost_relevance
            if action.boost_novelty is not None:
                total_boost_nov += action.boost_novelty
            if action.boost_actionability is not None:
                total_boost_act += action.boost_actionability
            if action.set_composite_weight is not None:
                merged.set_composite_weight = action.set_composite_weight
            if action.set_category is not None:
                merged.set_category = action.set_category
            if action.set_category_id is not None:
                merged.set_category_id = action.set_category_id
            if action.add_tags:
                all_tags.extend(action.add_tags)
            if action.auto_create_task is not None:
                merged.auto_create_task = action.auto_create_task
            if action.auto_dismiss is not None:
                merged.auto_dismiss = action.auto_dismiss
            if action.notify_discord is not None:
                merged.notify_discord = action.notify_discord
            if action.priority_label is not None:
                merged.priority_label = action.priority_label
            if action.assign_to_topic is not None:
                merged.assign_to_topic = action.assign_to_topic

        if total_boost_rel:
            merged.boost_relevance = total_boost_rel
        if total_boost_nov:
            merged.boost_novelty = total_boost_nov
        if total_boost_act:
            merged.boost_actionability = total_boost_act
        if all_tags:
            merged.add_tags = list(dict.fromkeys(all_tags))  # deduplicate

        return merged

    async def apply_rules(self, finding: Dict, eval_result: RuleEvaluationResult) -> Dict:
        """Apply merged rule actions to a finding, mutating it in place."""
        actions = eval_result.merged_actions
        finding = dict(finding)  # shallow copy

        # Store which rules fired
        finding["fired_rule_ids"] = eval_result.matched_rule_ids

        # Score adjustments (clamp to 0-100)
        if actions.boost_relevance:
            key = "relevanceScore" if "relevanceScore" in finding else "relevance_score"
            finding[key] = max(0, min(100, finding.get(key, 50) + actions.boost_relevance))
        if actions.boost_novelty:
            key = "noveltyScore" if "noveltyScore" in finding else "novelty_score"
            finding[key] = max(0, min(100, finding.get(key, 50) + actions.boost_novelty))
        if actions.boost_actionability:
            key = "actionabilityScore" if "actionabilityScore" in finding else "actionability_score"
            finding[key] = max(0, min(100, finding.get(key, 50) + actions.boost_actionability))

        # Recompute composite if scores changed
        if actions.boost_relevance or actions.boost_novelty or actions.boost_actionability:
            weights = actions.set_composite_weight or {"relevance": 0.35, "novelty": 0.25, "actionability": 0.40}
            rel = finding.get("relevanceScore", finding.get("relevance_score", 50))
            nov = finding.get("noveltyScore", finding.get("novelty_score", 50))
            act = finding.get("actionabilityScore", finding.get("actionability_score", 50))
            composite = rel * weights.get("relevance", 0.35) + nov * weights.get("novelty", 0.25) + act * weights.get("actionability", 0.40)
            comp_key = "compositeScore" if "compositeScore" in finding else "composite_score"
            finding[comp_key] = round(composite, 1)

        # Category overrides
        if actions.set_category:
            finding["category"] = actions.set_category
        if actions.set_category_id:
            finding["category_id"] = actions.set_category_id

        # Tag additions
        if actions.add_tags:
            existing_tags = finding.get("tags", [])
            merged_tags = list(dict.fromkeys(existing_tags + actions.add_tags))
            finding["tags"] = merged_tags[:10]  # limit

        # Priority label
        if actions.priority_label:
            finding["priority_label"] = actions.priority_label

        return finding

    # ==================================================================
    # Self-Improvement & Feedback
    # ==================================================================

    async def _increment_fire_count(self, rule_id: str):
        """Increment the times_fired counter for a rule."""
        try:
            async with get_session() as session:
                await session.execute(
                    update(ResearchRuleModel)
                    .where(ResearchRuleModel.id == rule_id)
                    .values(times_fired=ResearchRuleModel.times_fired + 1)
                )
        except Exception as e:
            logger.warning("Failed to increment fire count", rule_id=rule_id, error=str(e))

    async def record_feedback(self, finding_id: str, was_useful: bool):
        """Propagate feedback to all rules that fired for a finding."""
        async with get_session() as session:
            row = await session.get(ResearchFindingModel, finding_id)
            if row is None or not row.fired_rule_ids:
                return

            for rule_id in row.fired_rule_ids:
                rule = await session.get(ResearchRuleModel, rule_id)
                if rule is None:
                    continue

                if was_useful:
                    rule.times_useful += 1

                # Recalculate effectiveness
                if rule.times_fired > 0:
                    rule.effectiveness_score = (rule.times_useful / rule.times_fired) * 100
                    rule.effectiveness_score = min(100, max(0, rule.effectiveness_score))

                rule.updated_at = datetime.utcnow()

    async def recalibrate_rules(self) -> Dict[str, Any]:
        """Weekly auto-recalibration of rules based on effectiveness.

        - Rules with effectiveness < 20 and >= 10 fires → auto-disabled
        - Rules with effectiveness > 80 and >= 10 fires → boost priority
        - Returns summary of changes made.
        """
        changes = {"disabled": [], "boosted": [], "total_evaluated": 0}

        async with get_session() as session:
            result = await session.execute(
                select(ResearchRuleModel).where(
                    ResearchRuleModel.times_fired >= 10
                )
            )
            rules = result.scalars().all()
            changes["total_evaluated"] = len(rules)

            for rule in rules:
                # Auto-disable ineffective rules
                if rule.effectiveness_score < 20 and rule.enabled:
                    rule.enabled = False
                    rule.updated_at = datetime.utcnow()
                    changes["disabled"].append({"id": rule.id, "name": rule.name, "score": rule.effectiveness_score})
                    logger.info("Rule auto-disabled", rule_id=rule.id, score=rule.effectiveness_score)

                # Boost effective rules (lower priority number = higher priority)
                elif rule.effectiveness_score > 80 and rule.priority > 10:
                    old_priority = rule.priority
                    rule.priority = max(10, rule.priority - 10)
                    rule.updated_at = datetime.utcnow()
                    changes["boosted"].append({
                        "id": rule.id, "name": rule.name,
                        "old_priority": old_priority, "new_priority": rule.priority,
                    })
                    logger.info("Rule priority boosted", rule_id=rule.id, old=old_priority, new=rule.priority)

        logger.info("Rules recalibration complete", **changes)
        return changes

    # ==================================================================
    # LLM-Assisted Rule Suggestions
    # ==================================================================

    async def suggest_rules(self, limit: int = 3) -> List[RuleSuggestion]:
        """Analyze high-value findings patterns and suggest new rules.

        Uses Ollama via the shared OllamaClient to analyze patterns.
        """
        # Get top findings from last 7 days that had no rules fire
        async with get_session() as session:
            from datetime import timedelta
            week_ago = datetime.utcnow() - timedelta(days=7)
            result = await session.execute(
                select(ResearchFindingModel)
                .where(
                    ResearchFindingModel.discovered_at >= week_ago,
                    ResearchFindingModel.composite_score >= 60,
                    ResearchFindingModel.fired_rule_ids == [],
                )
                .order_by(ResearchFindingModel.composite_score.desc())
                .limit(20)
            )
            uncovered_findings = result.scalars().all()

        if not uncovered_findings:
            logger.info("No uncovered findings for rule suggestions")
            return []

        # Build pattern summary for LLM
        patterns = []
        for f in uncovered_findings:
            patterns.append(f"- [{f.category}] {f.title} (score: {f.composite_score}, tags: {f.tags})")

        pattern_text = "\n".join(patterns[:10])

        try:
            from app.infrastructure.ollama_client import get_ollama_client
            ollama = get_ollama_client()

            prompt = f"""Analyze these high-scoring research findings that weren't caught by any rules.
Suggest up to {limit} new categorization/scoring rules.

Uncovered findings:
{pattern_text}

For each rule, provide:
1. A descriptive name
2. What conditions should trigger it (keywords in title/snippet, URL patterns)
3. What actions to take (category assignment, tag additions, score boosts)
4. Brief reasoning

Format as JSON array of objects with keys: name, description, rule_type, conditions, actions, reasoning, confidence"""

            response = await ollama.chat(
                prompt,
                system="You are a rules engine optimizer. Suggest practical categorization rules based on observed patterns. Return valid JSON only.",
                task_type="analysis",
                num_predict=1000,
            )

            # Parse response — best effort
            import json
            try:
                suggestions_data = json.loads(response.strip())
                if not isinstance(suggestions_data, list):
                    suggestions_data = [suggestions_data]
            except json.JSONDecodeError:
                logger.warning("Failed to parse LLM rule suggestions")
                return []

            suggestions = []
            for s in suggestions_data[:limit]:
                try:
                    suggestions.append(RuleSuggestion(
                        name=s.get("name", "Unnamed rule"),
                        description=s.get("description", ""),
                        rule_type=RuleType(s.get("rule_type", "categorization")),
                        conditions=RuleCondition(**s.get("conditions", {})),
                        actions=RuleAction(**s.get("actions", {})),
                        reasoning=s.get("reasoning", ""),
                        confidence=float(s.get("confidence", 0.5)),
                    ))
                except Exception as e:
                    logger.warning("Failed to parse suggestion", error=str(e))

            return suggestions

        except Exception as e:
            logger.error("Failed to generate rule suggestions", error=str(e))
            return []

    # ==================================================================
    # Stats
    # ==================================================================

    async def get_stats(self) -> RuleStats:
        """Get rules engine statistics."""
        async with get_session() as session:
            # Count totals
            total = (await session.execute(
                select(sql_func.count()).select_from(ResearchRuleModel)
            )).scalar_one()

            enabled = (await session.execute(
                select(sql_func.count()).select_from(ResearchRuleModel)
                .where(ResearchRuleModel.enabled == True)
            )).scalar_one()

            # By type
            type_result = await session.execute(
                select(ResearchRuleModel.rule_type, sql_func.count())
                .group_by(ResearchRuleModel.rule_type)
            )
            by_type = {r[0]: r[1] for r in type_result.all()}

            # By creator
            creator_result = await session.execute(
                select(ResearchRuleModel.created_by, sql_func.count())
                .group_by(ResearchRuleModel.created_by)
            )
            by_creator = {r[0]: r[1] for r in creator_result.all()}

            # Top effective (min 5 fires)
            top_result = await session.execute(
                select(ResearchRuleModel)
                .where(ResearchRuleModel.times_fired >= 5)
                .order_by(ResearchRuleModel.effectiveness_score.desc())
                .limit(5)
            )
            top_effective = [
                {"id": r.id, "name": r.name, "score": r.effectiveness_score, "fires": r.times_fired}
                for r in top_result.scalars().all()
            ]

            # Low effective (min 5 fires)
            low_result = await session.execute(
                select(ResearchRuleModel)
                .where(ResearchRuleModel.times_fired >= 5)
                .order_by(ResearchRuleModel.effectiveness_score.asc())
                .limit(5)
            )
            low_effective = [
                {"id": r.id, "name": r.name, "score": r.effectiveness_score, "fires": r.times_fired}
                for r in low_result.scalars().all()
            ]

            # Total fires
            fire_result = await session.execute(
                select(
                    sql_func.sum(ResearchRuleModel.times_fired),
                    sql_func.sum(ResearchRuleModel.times_useful),
                )
            )
            row = fire_result.one()

            return RuleStats(
                total_rules=total,
                enabled_rules=enabled,
                by_type=by_type,
                by_creator=by_creator,
                top_effective=top_effective,
                low_effective=low_effective,
                total_fires=row[0] or 0,
                total_useful=row[1] or 0,
            )

    # ==================================================================
    # Seeding
    # ==================================================================

    async def seed_default_rules(self) -> int:
        """Seed default rules if none exist. Returns count of rules created."""
        existing = await self.list_rules()
        if existing:
            return 0

        count = 0
        for rule_data in DEFAULT_RULES:
            rule_id = _generate_id("rule")
            async with get_session() as session:
                row = ResearchRuleModel(
                    id=rule_id,
                    name=rule_data["name"],
                    description=rule_data.get("description"),
                    rule_type=rule_data["rule_type"],
                    conditions=rule_data["conditions"],
                    actions=rule_data["actions"],
                    priority=rule_data.get("priority", 100),
                    enabled=True,
                    created_by=rule_data.get("created_by", "system"),
                )
                session.add(row)

            count += 1

        logger.info("Seeded default research rules", count=count)
        return count

    # ==================================================================
    # Helpers
    # ==================================================================

    @staticmethod
    def _orm_to_rule(row: ResearchRuleModel) -> ResearchRule:
        """Convert ORM row to Pydantic model."""
        return ResearchRule(
            id=row.id,
            name=row.name,
            description=row.description,
            rule_type=row.rule_type,
            conditions=RuleCondition(**row.conditions),
            actions=RuleAction(**row.actions),
            priority=row.priority,
            enabled=row.enabled,
            category_id=row.category_id,
            times_fired=row.times_fired,
            times_useful=row.times_useful,
            effectiveness_score=row.effectiveness_score,
            created_by=row.created_by,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


@lru_cache()
def get_research_rules_service() -> ResearchRulesService:
    """Get cached research rules service instance."""
    return ResearchRulesService()
