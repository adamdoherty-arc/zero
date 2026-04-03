"""Daily journal API."""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter()

class JournalEntry(BaseModel):
    date: Optional[str] = None
    mood: Optional[str] = None
    energy: Optional[int] = None
    highlights: Optional[List[str]] = None
    challenges: Optional[List[str]] = None
    gratitude: Optional[List[str]] = None
    reflection: Optional[str] = None

@router.post("/")
async def create_entry(req: JournalEntry):
    from app.services.journal_service import get_journal_service
    return await get_journal_service().create_or_update_entry(
        date_key=req.date, mood=req.mood, energy=req.energy,
        highlights=req.highlights, challenges=req.challenges,
        gratitude=req.gratitude, reflection=req.reflection,
    )

@router.get("/today")
async def get_today():
    from app.services.journal_service import get_journal_service
    entry = await get_journal_service().get_entry()
    return entry or {"date": None, "message": "No entry today yet"}

@router.get("/entries")
async def list_entries(limit: int = 14):
    from app.services.journal_service import get_journal_service
    return await get_journal_service().list_entries(limit=limit)

@router.get("/{date}")
async def get_entry(date: str):
    from app.services.journal_service import get_journal_service
    entry = await get_journal_service().get_entry(date)
    return entry or {"date": date, "message": "No entry for this date"}

@router.post("/auto-summary")
async def generate_summary(date: Optional[str] = None):
    from app.services.journal_service import get_journal_service
    summary = await get_journal_service().generate_auto_summary(date)
    return {"summary": summary}

@router.get("/trends/mood")
async def mood_trends(days: int = 30):
    from app.services.journal_service import get_journal_service
    return await get_journal_service().get_mood_trends(days=days)
