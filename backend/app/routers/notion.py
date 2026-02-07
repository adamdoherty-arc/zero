"""
Notion integration API endpoints.
"""

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import structlog

from app.services.notion_service import get_notion_service

logger = structlog.get_logger()
router = APIRouter()


class SyncSprintRequest(BaseModel):
    name: str
    status: str = "planned"
    description: Optional[str] = None
    database_id: Optional[str] = None


class SyncTasksRequest(BaseModel):
    tasks: List[Dict[str, Any]]
    database_id: Optional[str] = None


class MeetingNotesRequest(BaseModel):
    title: str
    date: str
    attendees: List[str]
    notes: str
    parent_page_id: Optional[str] = None


class SearchRequest(BaseModel):
    query: str


def _require_notion():
    svc = get_notion_service()
    if svc is None:
        raise HTTPException(
            status_code=503,
            detail="Notion not configured. Set ZERO_NOTION_API_KEY in .env"
        )
    return svc


@router.get("/status")
async def notion_status():
    """Check Notion connection status."""
    svc = get_notion_service()
    if svc is None:
        return {"connected": False, "reason": "Not configured"}
    try:
        # Try listing users to verify API key
        client = svc._get_client()
        await client.users.list()
        return {"connected": True}
    except Exception as e:
        return {"connected": False, "reason": str(e)}


@router.post("/sync-sprint")
async def sync_sprint(req: SyncSprintRequest):
    """Sync a sprint to Notion."""
    svc = _require_notion()
    result = await svc.sync_sprint_to_notion(
        sprint_data=req.model_dump(),
        database_id=req.database_id,
    )
    return {"synced": True, "page_id": result.get("id")}


@router.post("/sync-tasks")
async def sync_tasks(req: SyncTasksRequest):
    """Sync tasks to a Notion database."""
    svc = _require_notion()
    results = await svc.sync_tasks_to_notion(
        tasks=req.tasks,
        database_id=req.database_id,
    )
    return {"synced": len(results), "page_ids": [r.get("id") for r in results]}


@router.get("/pull")
async def pull_from_notion(database_id: Optional[str] = None):
    """Pull items from a Notion database."""
    svc = _require_notion()
    items = await svc.pull_from_notion(database_id=database_id)
    return {"items": items, "count": len(items)}


@router.post("/meeting-notes")
async def create_meeting_notes(req: MeetingNotesRequest):
    """Create meeting notes page in Notion."""
    svc = _require_notion()
    result = await svc.create_meeting_notes(
        title=req.title,
        date=req.date,
        attendees=req.attendees,
        notes=req.notes,
        parent_page_id=req.parent_page_id,
    )
    return {"created": True, "page_id": result.get("id")}


@router.post("/search")
async def search_knowledge(req: SearchRequest):
    """Search Notion knowledge base."""
    svc = _require_notion()
    results = await svc.search_knowledge_base(req.query)
    return {"results": results, "count": len(results)}
