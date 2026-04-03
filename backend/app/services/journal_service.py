"""
Daily Journal Service

Auto-generates daily summaries from Zero's activity, supports manual entries.
"""

import uuid
from datetime import datetime, timedelta, UTC
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import select, desc

from app.infrastructure.database import AsyncSessionLocal

logger = structlog.get_logger(__name__)


class JournalService:

    async def create_or_update_entry(
        self, date_key: str = None, mood: str = None, energy: int = None,
        highlights: list = None, challenges: list = None,
        gratitude: list = None, reflection: str = None,
    ) -> Dict[str, Any]:
        from app.db.models import JournalEntryModel
        date_key = date_key or datetime.now(UTC).strftime("%Y-%m-%d")
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(JournalEntryModel).where(JournalEntryModel.date_key == date_key)
            )
            entry = result.scalar_one_or_none()

            if entry:
                if mood is not None: entry.mood = mood
                if energy is not None: entry.energy = energy
                if highlights is not None: entry.highlights = highlights
                if challenges is not None: entry.challenges = challenges
                if gratitude is not None: entry.gratitude = gratitude
                if reflection is not None: entry.reflection = reflection
            else:
                entry = JournalEntryModel(
                    date_key=date_key, mood=mood, energy=energy,
                    highlights=highlights or [], challenges=challenges or [],
                    gratitude=gratitude or [], reflection=reflection,
                )
                db.add(entry)

            await db.commit()
            return {"date": date_key, "updated": True}

    async def get_entry(self, date_key: str = None) -> Optional[Dict[str, Any]]:
        from app.db.models import JournalEntryModel
        date_key = date_key or datetime.now(UTC).strftime("%Y-%m-%d")
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(JournalEntryModel).where(JournalEntryModel.date_key == date_key)
            )
            e = result.scalar_one_or_none()
            if not e:
                return None
            return {
                "date": e.date_key, "mood": e.mood, "energy": e.energy,
                "highlights": e.highlights, "challenges": e.challenges,
                "gratitude": e.gratitude, "reflection": e.reflection,
                "auto_summary": e.auto_summary, "tags": e.tags,
            }

    async def list_entries(self, limit: int = 14) -> List[Dict[str, Any]]:
        from app.db.models import JournalEntryModel
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(JournalEntryModel).order_by(desc(JournalEntryModel.date_key)).limit(limit)
            )
            return [
                {"date": e.date_key, "mood": e.mood, "energy": e.energy,
                 "highlights_count": len(e.highlights or []),
                 "has_reflection": bool(e.reflection)}
                for e in result.scalars().all()
            ]

    async def generate_auto_summary(self, date_key: str = None) -> str:
        """Generate an AI summary of the day from Zero's activity logs."""
        date_key = date_key or datetime.now(UTC).strftime("%Y-%m-%d")
        parts = []

        # Gather day's data
        try:
            from app.services.habit_service import get_habit_service
            status = await get_habit_service().get_today_status()
            if status["total"] > 0:
                parts.append(f"Habits: {status['completed']}/{status['total']} completed")
        except Exception:
            pass

        try:
            from app.services.goal_tracking_service import get_goal_tracking_service
            goals = await get_goal_tracking_service().list_goals(status="active")
            if goals:
                parts.append(f"Active goals: {len(goals)}")
        except Exception:
            pass

        try:
            from app.services.cross_domain_service import get_cross_domain_service
            focus = await get_cross_domain_service().what_should_i_focus_on()
            if focus.get("recommendations"):
                top = focus["recommendations"][0]
                parts.append(f"Top focus: {top['action']}")
        except Exception:
            pass

        summary = " | ".join(parts) if parts else "No activity data for today."

        # Save auto summary
        from app.db.models import JournalEntryModel
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(JournalEntryModel).where(JournalEntryModel.date_key == date_key)
            )
            entry = result.scalar_one_or_none()
            if entry:
                entry.auto_summary = summary
            else:
                entry = JournalEntryModel(date_key=date_key, auto_summary=summary)
                db.add(entry)
            await db.commit()

        return summary

    async def get_mood_trends(self, days: int = 30) -> Dict[str, Any]:
        from app.db.models import JournalEntryModel
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(JournalEntryModel)
                .where(JournalEntryModel.mood.isnot(None))
                .order_by(desc(JournalEntryModel.date_key))
                .limit(days)
            )
            entries = result.scalars().all()
            mood_map = {"great": 5, "good": 4, "okay": 3, "rough": 2, "bad": 1}
            moods = [mood_map.get(e.mood, 3) for e in entries]
            return {
                "entries": len(entries),
                "avg_mood": round(sum(moods) / len(moods), 1) if moods else 0,
                "trend": moods[:7],
                "best_day": max(entries, key=lambda e: mood_map.get(e.mood, 0)).date_key if entries else None,
            }


_journal_service: Optional[JournalService] = None

def get_journal_service() -> JournalService:
    global _journal_service
    if _journal_service is None:
        _journal_service = JournalService()
    return _journal_service
