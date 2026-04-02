"""
Feedback & Preference Learning Service

Tracks user feedback on responses, learns preferences over time,
and provides preference-aware context for response generation.
"""

import uuid
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import select, update, desc, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database import AsyncSessionLocal

logger = structlog.get_logger(__name__)


class FeedbackService:
    """Collects feedback and learns user preferences."""

    # ------------------------------------------------------------------
    # Feedback collection
    # ------------------------------------------------------------------

    async def record_feedback(
        self,
        rating: int,  # -1 (bad), 0 (neutral), 1 (good)
        session_id: Optional[str] = None,
        message_id: Optional[int] = None,
        feedback_type: str = "response_quality",
        comment: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> Dict[str, Any]:
        from app.db.models import FeedbackModel
        async with AsyncSessionLocal() as db:
            fb = FeedbackModel(
                session_id=session_id,
                message_id=message_id,
                rating=max(-1, min(1, rating)),
                feedback_type=feedback_type,
                comment=comment,
                context=context or {},
            )
            db.add(fb)
            await db.commit()
            await db.refresh(fb)

            # Trigger preference learning on sufficient data
            await self._maybe_update_preferences(feedback_type)

            return {"id": fb.id, "rating": fb.rating, "recorded": True}

    async def get_feedback_stats(self) -> Dict[str, Any]:
        from app.db.models import FeedbackModel
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(
                    FeedbackModel.feedback_type,
                    func.count(FeedbackModel.id).label("total"),
                    func.avg(FeedbackModel.rating).label("avg_rating"),
                )
                .group_by(FeedbackModel.feedback_type)
            )
            rows = result.all()
            stats = {}
            for ft, total, avg in rows:
                stats[ft] = {"total": total, "avg_rating": round(float(avg or 0), 2)}
            return stats

    # ------------------------------------------------------------------
    # Preference learning
    # ------------------------------------------------------------------

    async def _maybe_update_preferences(self, feedback_type: str):
        """Analyze recent feedback and update learned preferences."""
        from app.db.models import FeedbackModel, LearnedPreferenceModel
        async with AsyncSessionLocal() as db:
            # Get recent feedback of this type
            result = await db.execute(
                select(FeedbackModel)
                .where(FeedbackModel.feedback_type == feedback_type)
                .order_by(desc(FeedbackModel.created_at))
                .limit(20)
            )
            recent = result.scalars().all()
            if len(recent) < 5:
                return  # Not enough data

            # Analyze patterns
            positive = [f for f in recent if f.rating > 0]
            negative = [f for f in recent if f.rating < 0]

            # Learn response length preference
            pos_lengths = [f.context.get("response_length", 0) for f in positive if f.context]
            neg_lengths = [f.context.get("response_length", 0) for f in negative if f.context]

            if pos_lengths and neg_lengths:
                avg_good = sum(pos_lengths) / len(pos_lengths)
                avg_bad = sum(neg_lengths) / len(neg_lengths)
                if avg_good > 0:
                    if avg_good < avg_bad * 0.7:
                        pref_value = "concise"
                    elif avg_good > avg_bad * 1.3:
                        pref_value = "detailed"
                    else:
                        pref_value = "moderate"

                    await self._upsert_preference(
                        db, "response_style", "preferred_length", pref_value,
                        confidence=min(1.0, len(recent) / 20),
                        evidence_count=len(recent),
                    )

            # Learn from route-specific feedback
            pos_routes = {}
            for f in positive:
                route = (f.context or {}).get("route", "unknown")
                pos_routes[route] = pos_routes.get(route, 0) + 1

            neg_routes = {}
            for f in negative:
                route = (f.context or {}).get("route", "unknown")
                neg_routes[route] = neg_routes.get(route, 0) + 1

            # Store route satisfaction scores
            all_routes = set(list(pos_routes.keys()) + list(neg_routes.keys()))
            for route in all_routes:
                if route == "unknown":
                    continue
                pos = pos_routes.get(route, 0)
                neg = neg_routes.get(route, 0)
                total = pos + neg
                if total >= 3:
                    score = pos / total
                    await self._upsert_preference(
                        db, "route_satisfaction", route, f"{score:.2f}",
                        confidence=min(1.0, total / 10),
                        evidence_count=total,
                    )

            await db.commit()

    async def _upsert_preference(
        self,
        db: AsyncSession,
        category: str,
        key: str,
        value: str,
        confidence: float = 0.5,
        evidence_count: int = 1,
    ):
        from app.db.models import LearnedPreferenceModel
        result = await db.execute(
            select(LearnedPreferenceModel).where(
                and_(
                    LearnedPreferenceModel.category == category,
                    LearnedPreferenceModel.key == key,
                )
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.value = value
            existing.confidence = confidence
            existing.evidence_count = evidence_count
            existing.last_updated = datetime.now(UTC).replace(tzinfo=None)
        else:
            db.add(LearnedPreferenceModel(
                category=category,
                key=key,
                value=value,
                confidence=confidence,
                evidence_count=evidence_count,
            ))

    async def get_preferences(self, category: Optional[str] = None) -> Dict[str, Any]:
        """Get all learned preferences, optionally filtered by category."""
        from app.db.models import LearnedPreferenceModel
        async with AsyncSessionLocal() as db:
            query = select(LearnedPreferenceModel)
            if category:
                query = query.where(LearnedPreferenceModel.category == category)
            result = await db.execute(query.order_by(LearnedPreferenceModel.category))
            prefs = result.scalars().all()
            grouped = {}
            for p in prefs:
                if p.category not in grouped:
                    grouped[p.category] = {}
                grouped[p.category][p.key] = {
                    "value": p.value,
                    "confidence": p.confidence,
                    "evidence_count": p.evidence_count,
                }
            return grouped

    async def get_response_guidelines(self) -> str:
        """Generate response guidelines string from learned preferences for LLM context."""
        prefs = await self.get_preferences()
        lines = []

        style = prefs.get("response_style", {})
        if "preferred_length" in style:
            pref = style["preferred_length"]
            if pref["confidence"] > 0.3:
                lines.append(f"- User prefers {pref['value']} responses")

        tone = prefs.get("tone", {})
        if "preferred_tone" in tone:
            pref = tone["preferred_tone"]
            if pref["confidence"] > 0.3:
                lines.append(f"- Preferred tone: {pref['value']}")

        schedule = prefs.get("schedule", {})
        if "active_hours" in schedule:
            pref = schedule["active_hours"]
            lines.append(f"- Most active during: {pref['value']}")

        if lines:
            return "## User Preferences (learned)\n" + "\n".join(lines)
        return ""


_feedback_service: Optional[FeedbackService] = None

def get_feedback_service() -> FeedbackService:
    global _feedback_service
    if _feedback_service is None:
        _feedback_service = FeedbackService()
    return _feedback_service
