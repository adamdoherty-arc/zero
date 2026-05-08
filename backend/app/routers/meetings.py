"""Meeting CRUD endpoints."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, delete
import structlog

from app.db.models import (
    MeetingModel, MeetingRecordingModel, MeetingTranscriptSegmentModel,
    MeetingSummaryModel, MeetingSpeakerMappingModel,
)
from app.infrastructure.database import get_session
from app.models.meeting import (
    MeetingCreate, MeetingUpdate, MeetingResponse, MeetingListResponse,
)

router = APIRouter()
logger = structlog.get_logger(__name__)


class MeetingFromEventRequest(BaseModel):
    calendar_event_id: str


class AutoRecordToggle(BaseModel):
    enabled: bool


@router.get("/")
async def list_meetings(
    status: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    async with get_session() as db:
        query = select(MeetingModel)
        if status:
            query = query.where(MeetingModel.status == status)
        if search:
            query = query.where(MeetingModel.title.ilike(f"%{search}%"))
        query = query.order_by(MeetingModel.start_time.desc())

        # Count
        count_q = select(func.count()).select_from(query.subquery())
        total = (await db.execute(count_q)).scalar() or 0

        # Paginate
        query = query.limit(limit).offset(offset)
        result = await db.execute(query)
        meetings = result.scalars().all()

        return MeetingListResponse(
            meetings=[MeetingResponse.model_validate(m) for m in meetings],
            total=total,
        )


class MeetingArtifactStats(BaseModel):
    meeting_id: str
    transcript_segments: int
    has_summary: bool
    action_items_count: int
    speaker_count: int


@router.get("/artifacts/stats", response_model=list[MeetingArtifactStats])
async def list_artifact_stats(
    meeting_ids: str = Query(..., description="comma-separated meeting ids"),
):
    """Quick badge data for the meetings list — counts in a single roundtrip
    instead of N detail fetches per page."""
    ids = [i.strip() for i in meeting_ids.split(",") if i.strip()]
    if not ids:
        return []

    async with get_session() as db:
        seg_rows = (
            await db.execute(
                select(
                    MeetingTranscriptSegmentModel.meeting_id,
                    func.count().label("n"),
                )
                .where(MeetingTranscriptSegmentModel.meeting_id.in_(ids))
                .group_by(MeetingTranscriptSegmentModel.meeting_id)
            )
        ).all()
        seg_counts = {row[0]: int(row[1]) for row in seg_rows}

        speaker_rows = (
            await db.execute(
                select(
                    MeetingTranscriptSegmentModel.meeting_id,
                    func.count(func.distinct(MeetingTranscriptSegmentModel.speaker)).label("n"),
                )
                .where(
                    MeetingTranscriptSegmentModel.meeting_id.in_(ids),
                    MeetingTranscriptSegmentModel.speaker.is_not(None),
                )
                .group_by(MeetingTranscriptSegmentModel.meeting_id)
            )
        ).all()
        speaker_counts = {row[0]: int(row[1]) for row in speaker_rows}

        summaries = (
            await db.execute(
                select(MeetingSummaryModel).where(
                    MeetingSummaryModel.meeting_id.in_(ids)
                )
            )
        ).scalars().all()
        summary_index: dict[str, MeetingSummaryModel] = {s.meeting_id: s for s in summaries}

    out: list[MeetingArtifactStats] = []
    for mid in ids:
        s = summary_index.get(mid)
        out.append(MeetingArtifactStats(
            meeting_id=mid,
            transcript_segments=seg_counts.get(mid, 0),
            has_summary=bool(s and (s.summary_text or "").strip()),
            action_items_count=len(list(s.action_items or [])) if s else 0,
            speaker_count=speaker_counts.get(mid, 0),
        ))
    return out


@router.post("/", status_code=201)
async def create_meeting(data: MeetingCreate):
    async with get_session() as db:
        meeting = MeetingModel(
            id=uuid.uuid4().hex,
            title=data.title,
            start_time=data.start_time,
            end_time=data.end_time,
            participants=data.participants or [],
            calendar_event_id=data.calendar_event_id,
        )
        db.add(meeting)
        await db.commit()
        await db.refresh(meeting)
        return MeetingResponse.model_validate(meeting)


@router.post("/from-event", status_code=201)
async def create_meeting_from_event(req: MeetingFromEventRequest):
    """Create a MeetingModel linked to a calendar event so it can be recorded.

    Idempotent: if a meeting with this calendar_event_id already exists, returns it.
    Pulls title + start/end from the cached calendar event.
    """
    from app.services.calendar_service import get_calendar_service
    cal = get_calendar_service()

    async with get_session() as db:
        existing = (
            await db.execute(
                select(MeetingModel).where(MeetingModel.calendar_event_id == req.calendar_event_id)
            )
        ).scalar_one_or_none()
        if existing:
            return MeetingResponse.model_validate(existing)

        event = await cal.get_event(req.calendar_event_id)
        if not event:
            raise HTTPException(404, f"Calendar event {req.calendar_event_id} not found")

        # Resolve start/end from EventDateTime (date_time wins, fall back to date).
        start_time = _event_dt_to_datetime(event.start)
        end_time = _event_dt_to_datetime(event.end) if event.end else None
        if start_time is None:
            raise HTTPException(400, "Calendar event missing start time")

        meeting = MeetingModel(
            id=uuid.uuid4().hex,
            title=event.summary or "Untitled meeting",
            start_time=start_time,
            end_time=end_time,
            participants=[a.email for a in (event.attendees or []) if getattr(a, "email", None)],
            calendar_event_id=req.calendar_event_id,
            status="scheduled",
        )
        db.add(meeting)
        await db.commit()
        await db.refresh(meeting)
        return MeetingResponse.model_validate(meeting)


@router.post("/{meeting_id}/record-now", status_code=200)
async def record_now(meeting_id: str):
    """Start recording immediately for a specific (already-created) meeting."""
    from app.routers.meeting_recordings import _host_agent_url, _forward
    from app.services.meeting_recording_service import start_recording

    if _host_agent_url():
        return await _forward(
            "POST", "/record/start", json={"meeting_id": meeting_id, "source": "mixed"}
        )
    async with get_session() as db:
        try:
            return await start_recording(db, meeting_id=meeting_id, source="mixed")
        except RuntimeError as e:
            raise HTTPException(409, str(e))
        except ValueError as e:
            raise HTTPException(404, str(e))


@router.post("/{meeting_id}/auto-record", status_code=200)
async def toggle_auto_record(meeting_id: str, body: AutoRecordToggle):
    """Flag (or unflag) a calendar-linked meeting for automatic recording at start time."""
    from app.services.meeting_auto_recorder_service import get_meeting_auto_recorder_service

    async with get_session() as db:
        result = await db.execute(select(MeetingModel).where(MeetingModel.id == meeting_id))
        meeting = result.scalar_one_or_none()
        if not meeting:
            raise HTTPException(404, "Meeting not found")
        if not meeting.calendar_event_id:
            raise HTTPException(
                400, "Auto-record requires a calendar-linked meeting (use /from-event first)"
            )

    svc = get_meeting_auto_recorder_service()
    if body.enabled:
        await svc.mark(
            calendar_event_id=meeting.calendar_event_id,
            meeting_id=meeting.id,
            start_time=meeting.start_time,
            end_time=meeting.end_time,
            title=meeting.title,
        )
    else:
        await svc.unmark(meeting.calendar_event_id)
    return {"meeting_id": meeting.id, "auto_record": body.enabled}


@router.get("/auto-record/list", status_code=200)
async def list_auto_record():
    """All meetings currently flagged for auto-record."""
    from app.services.meeting_auto_recorder_service import get_meeting_auto_recorder_service

    return {"entries": await get_meeting_auto_recorder_service().list_marked()}


def _event_dt_to_datetime(event_dt) -> datetime | None:
    """Pull a tz-aware UTC datetime out of an EventDateTime payload."""
    if event_dt is None:
        return None
    if getattr(event_dt, "date_time", None):
        dt = event_dt.date_time
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    if getattr(event_dt, "date", None):
        d = event_dt.date
        if isinstance(d, str):
            d = datetime.strptime(d, "%Y-%m-%d")
        return d.replace(tzinfo=timezone.utc)
    return None


@router.get("/{meeting_id}")
async def get_meeting(meeting_id: str):
    async with get_session() as db:
        result = await db.execute(select(MeetingModel).where(MeetingModel.id == meeting_id))
        meeting = result.scalar_one_or_none()
        if not meeting:
            raise HTTPException(404, "Meeting not found")
        return MeetingResponse.model_validate(meeting)


@router.patch("/{meeting_id}")
async def update_meeting(meeting_id: str, data: MeetingUpdate):
    async with get_session() as db:
        result = await db.execute(select(MeetingModel).where(MeetingModel.id == meeting_id))
        meeting = result.scalar_one_or_none()
        if not meeting:
            raise HTTPException(404, "Meeting not found")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(meeting, field, value)
        meeting.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(meeting)
        return MeetingResponse.model_validate(meeting)


@router.delete("/{meeting_id}", status_code=204)
async def delete_meeting(meeting_id: str):
    async with get_session() as db:
        result = await db.execute(select(MeetingModel).where(MeetingModel.id == meeting_id))
        meeting = result.scalar_one_or_none()
        if not meeting:
            raise HTTPException(404, "Meeting not found")
        # Delete vectors
        try:
            from app.services.meeting_vector_service import get_meeting_vector_service
            await get_meeting_vector_service().delete_meeting_vectors(meeting_id, db)
        except Exception:
            pass
        await db.delete(meeting)
        await db.commit()


@router.get("/{meeting_id}/export")
async def export_meeting(meeting_id: str, format: str = Query("markdown")):
    async with get_session() as db:
        result = await db.execute(select(MeetingModel).where(MeetingModel.id == meeting_id))
        meeting = result.scalar_one_or_none()
        if not meeting:
            raise HTTPException(404, "Meeting not found")

        # Get transcript
        seg_result = await db.execute(
            select(MeetingTranscriptSegmentModel)
            .where(MeetingTranscriptSegmentModel.meeting_id == meeting_id)
            .order_by(MeetingTranscriptSegmentModel.start_time)
        )
        segments = seg_result.scalars().all()

        # Get summary
        sum_result = await db.execute(
            select(MeetingSummaryModel).where(MeetingSummaryModel.meeting_id == meeting_id)
        )
        summary = sum_result.scalar_one_or_none()

        # Get speaker mappings
        spk_result = await db.execute(
            select(MeetingSpeakerMappingModel).where(MeetingSpeakerMappingModel.meeting_id == meeting_id)
        )
        speaker_map = {s.speaker_label: s.display_name for s in spk_result.scalars().all()}

        # Build markdown
        lines = [f"# {meeting.title}", f"**Date:** {meeting.start_time.strftime('%Y-%m-%d %H:%M')}"]
        if meeting.duration_seconds:
            lines.append(f"**Duration:** {meeting.duration_seconds // 60}m {meeting.duration_seconds % 60}s")
        lines.append("")

        if summary:
            lines.append("## Summary")
            lines.append(summary.summary_text)
            lines.append("")
            if summary.key_topics:
                lines.append("### Key Topics")
                for topic in summary.key_topics:
                    lines.append(f"- {topic}")
                lines.append("")
            if summary.action_items:
                lines.append("### Action Items")
                for item in summary.action_items:
                    if isinstance(item, dict):
                        lines.append(f"- [ ] {item.get('description', '')} (Owner: {item.get('owner', 'Unassigned')})")
                    else:
                        lines.append(f"- [ ] {item}")
                lines.append("")

        if segments:
            lines.append("## Transcript")
            for seg in segments:
                speaker = speaker_map.get(seg.speaker, seg.speaker) or "Speaker"
                mins = int(seg.start_time // 60)
                secs = int(seg.start_time % 60)
                lines.append(f"**[{mins:02d}:{secs:02d}] {speaker}:** {seg.text}")
            lines.append("")

        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(
            content="\n".join(lines),
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{meeting.title}.md"'},
        )


# ---------------------------------------------------------------------------
# Action Items → Zero Tasks
# ---------------------------------------------------------------------------

class CreateTasksRequest(BaseModel):
    owner_filter: str = "all"  # "all" | "me"
    auto_assign: bool = True


class ActionItemTaskLink(BaseModel):
    index: int
    owner: str
    description: str
    due: str | None = None
    task_id: str | None = None
    skipped_reason: str | None = None


class CreateTasksResponse(BaseModel):
    meeting_id: str
    created: list[ActionItemTaskLink]
    skipped: list[ActionItemTaskLink]


def _is_me_owner(owner: str, primary_names: set[str]) -> bool:
    """Heuristic: owner field matches the primary user."""
    if not owner:
        return False
    o = owner.strip().lower()
    if o in {"me", "myself", "i"}:
        return True
    return any(o == p.lower() or o in p.lower() or p.lower() in o for p in primary_names)


async def _primary_names() -> set[str]:
    from app.db.models import VoiceprintModel
    async with get_session() as db:
        rows = (
            await db.execute(
                select(VoiceprintModel.display_name).where(
                    VoiceprintModel.is_primary == True  # noqa: E712
                )
            )
        ).all()
    return {r[0] for r in rows}


def _parse_due(due: str | None) -> str | None:
    """Pass through ISO-ish dates as a string for source_reference. Tasks store
    description-level info; we don't gate on due-date validity."""
    if not due:
        return None
    return str(due).strip() or None


@router.get("/{meeting_id}/action-items")
async def get_action_items(meeting_id: str):
    """Return action items from the meeting summary as a structured list."""
    async with get_session() as db:
        summary = (
            await db.execute(
                select(MeetingSummaryModel).where(MeetingSummaryModel.meeting_id == meeting_id)
            )
        ).scalar_one_or_none()
        if summary is None:
            raise HTTPException(404, "No summary for this meeting yet")
        items = list(summary.action_items or [])
        return {
            "meeting_id": meeting_id,
            "action_items": items,
            "total": len(items),
        }


@router.post("/{meeting_id}/action-items/create-tasks", response_model=CreateTasksResponse)
async def create_tasks_from_action_items(
    meeting_id: str,
    body: CreateTasksRequest,
):
    """Convert this meeting's LLM-extracted action items into Zero tasks."""
    from app.models.task import (
        TaskCreate, TaskCategory, TaskPriority, TaskSource,
    )
    from app.services.task_service import TaskService

    async with get_session() as db:
        meeting = (
            await db.execute(select(MeetingModel).where(MeetingModel.id == meeting_id))
        ).scalar_one_or_none()
        if meeting is None:
            raise HTTPException(404, "Meeting not found")

        summary = (
            await db.execute(
                select(MeetingSummaryModel).where(MeetingSummaryModel.meeting_id == meeting_id)
            )
        ).scalar_one_or_none()
        if summary is None:
            raise HTTPException(404, "No summary for this meeting yet")

    items = list(summary.action_items or [])
    primaries = await _primary_names() if body.owner_filter == "me" else set()
    task_service = TaskService()

    created: list[ActionItemTaskLink] = []
    skipped: list[ActionItemTaskLink] = []

    for idx, raw in enumerate(items):
        owner = (raw or {}).get("owner") or "Unassigned"
        description = (raw or {}).get("description") or ""
        due = _parse_due((raw or {}).get("due"))
        link = ActionItemTaskLink(
            index=idx, owner=owner, description=description, due=due
        )

        if not description.strip():
            link.skipped_reason = "empty description"
            skipped.append(link)
            continue

        if body.owner_filter == "me" and not _is_me_owner(owner, primaries):
            link.skipped_reason = "owner is not the primary user"
            skipped.append(link)
            continue

        title = description if len(description) <= 120 else description[:117] + "…"
        body_lines = [
            f"From meeting: {meeting.title}",
            f"Meeting ID: {meeting_id}",
            f"Owner (per transcript): {owner}",
        ]
        if due:
            body_lines.append(f"Due (per transcript): {due}")
        full_desc = "\n".join(body_lines) + "\n\n" + description

        try:
            task = await task_service.create_task(TaskCreate(
                title=title,
                description=full_desc,
                category=TaskCategory.CHORE,
                priority=TaskPriority.MEDIUM,
                source=TaskSource.USER_REPORTED,
                source_reference=f"meeting:{meeting_id}#action-{idx}",
            ))
            link.task_id = task.id
            created.append(link)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "create_task_from_action_item_failed",
                meeting_id=meeting_id,
                idx=idx,
                error=str(exc),
            )
            link.skipped_reason = f"create failed: {exc}"
            skipped.append(link)

    logger.info(
        "action_items_to_tasks",
        meeting_id=meeting_id,
        created=len(created),
        skipped=len(skipped),
    )
    return CreateTasksResponse(meeting_id=meeting_id, created=created, skipped=skipped)
