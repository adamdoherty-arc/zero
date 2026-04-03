"""
Habit Tracking Service

Track daily habits, maintain streaks, generate completion reports.
"""

import uuid
from datetime import datetime, timedelta, UTC
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import select, update, desc, func, and_

from app.infrastructure.database import AsyncSessionLocal

logger = structlog.get_logger(__name__)


class HabitService:

    async def create_habit(self, name: str, description: str = None,
                          frequency: str = "daily", target_count: int = 1,
                          category: str = "general") -> Dict[str, Any]:
        from app.db.models import HabitModel
        habit_id = str(uuid.uuid4())[:12]
        async with AsyncSessionLocal() as db:
            habit = HabitModel(
                id=habit_id, name=name, description=description,
                frequency=frequency, target_count=target_count, category=category,
            )
            db.add(habit)
            await db.commit()
            return {"id": habit_id, "name": name, "frequency": frequency}

    async def log_completion(self, habit_id: str, note: str = None) -> Dict[str, Any]:
        from app.db.models import HabitModel, HabitLogModel
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        async with AsyncSessionLocal() as db:
            habit = await db.get(HabitModel, habit_id)
            if not habit:
                return {"error": "Habit not found"}

            # Check if already logged today
            existing = await db.execute(
                select(HabitLogModel).where(
                    and_(HabitLogModel.habit_id == habit_id, HabitLogModel.date_key == today)
                )
            )
            if existing.scalar_one_or_none():
                return {"already_logged": True, "date": today}

            log = HabitLogModel(habit_id=habit_id, date_key=today, note=note)
            db.add(log)

            # Update streak
            yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
            prev = await db.execute(
                select(HabitLogModel).where(
                    and_(HabitLogModel.habit_id == habit_id, HabitLogModel.date_key == yesterday)
                )
            )
            if prev.scalar_one_or_none():
                habit.streak_current += 1
            else:
                habit.streak_current = 1

            if habit.streak_current > habit.streak_best:
                habit.streak_best = habit.streak_current

            await db.commit()
            return {
                "logged": True, "date": today, "habit": habit.name,
                "streak": habit.streak_current, "best_streak": habit.streak_best,
            }

    async def list_habits(self, active_only: bool = True) -> List[Dict[str, Any]]:
        from app.db.models import HabitModel
        async with AsyncSessionLocal() as db:
            query = select(HabitModel).order_by(HabitModel.name)
            if active_only:
                query = query.where(HabitModel.is_active == True)
            result = await db.execute(query)
            return [
                {
                    "id": h.id, "name": h.name, "frequency": h.frequency,
                    "category": h.category, "streak": h.streak_current,
                    "best_streak": h.streak_best, "target": h.target_count,
                }
                for h in result.scalars().all()
            ]

    async def get_today_status(self) -> Dict[str, Any]:
        from app.db.models import HabitModel, HabitLogModel
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        async with AsyncSessionLocal() as db:
            habits = await db.execute(
                select(HabitModel).where(HabitModel.is_active == True)
            )
            all_habits = habits.scalars().all()
            completed_ids = set()
            logs = await db.execute(
                select(HabitLogModel.habit_id).where(HabitLogModel.date_key == today)
            )
            for row in logs.scalars().all():
                completed_ids.add(row)

            items = []
            for h in all_habits:
                items.append({
                    "id": h.id, "name": h.name, "completed": h.id in completed_ids,
                    "streak": h.streak_current,
                })

            total = len(all_habits)
            done = len(completed_ids)
            return {
                "date": today, "total": total, "completed": done,
                "completion_pct": round(done / total * 100, 1) if total > 0 else 0,
                "habits": items,
            }

    async def get_habit_context_for_briefing(self) -> str:
        status = await self.get_today_status()
        if not status["habits"]:
            return ""
        lines = [f"## Habits ({status['completed']}/{status['total']} today)"]
        for h in status["habits"]:
            icon = "\u2705" if h["completed"] else "\u2b1c"
            streak = f" (\U0001f525{h['streak']})" if h["streak"] >= 3 else ""
            lines.append(f"  {icon} {h['name']}{streak}")
        return "\n".join(lines)


_habit_service: Optional[HabitService] = None

def get_habit_service() -> HabitService:
    global _habit_service
    if _habit_service is None:
        _habit_service = HabitService()
    return _habit_service
