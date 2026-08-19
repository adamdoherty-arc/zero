"""Personal work-item API.

Personal-scope counterpart to /api/company/work-items. Same `tasks` table,
project_id="personal", `domain` column used as the *topic* for UI filtering.

Adds a one-shot `/seed-va` endpoint that materializes the VA disability claim
playbook into ~21 tasks grouped by phase (7d / 30d / 60d / 90d / reference)
and three "narrative" tasks (GERD, Anxiety, Tinnitus) that act as living docs
the user refines over time by editing their description.
"""

from __future__ import annotations

import uuid
from pathlib import Path as _Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.infrastructure.auth import require_auth, require_auth_flex
from app.infrastructure.config import get_workspace_path
from app.models.task import Task, TaskAttachment, TaskCategory, TaskCreate, TaskPriority, TaskSource, TaskStatus, TaskUpdate
from app.services.personal_work_item_service import get_personal_work_item_service


router = APIRouter(
    prefix="/api/personal/work-items",
    tags=["personal-work-items"],
    dependencies=[Depends(require_auth)],
)


class ActorRequest(BaseModel):
    actor: str = Field(default="user", max_length=100)


class CompleteRequest(BaseModel):
    actor: str = Field(default="user", max_length=100)
    completion_note: Optional[str] = None


class NoteRequest(BaseModel):
    actor: str = Field(default="user", max_length=100)
    note: str = Field(..., min_length=1, max_length=4000)


VA_TOPIC = "VA Claim"


class SeedVAResponse(BaseModel):
    created: int
    skipped: int
    tasks: list[Task]


@router.get("")
async def list_work_items(
    status: Optional[str] = Query(default=None),
    topic: Optional[str] = Query(default=None),
    priority: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    filter_name: Optional[str] = Query(default=None),
    include_archived: bool = Query(default=False),
    limit: int = Query(default=500, ge=1, le=1000),
) -> list[Task]:
    return await get_personal_work_item_service().list_work_items(
        status=status,
        topic=topic,
        priority=priority,
        search=search,
        filter_name=filter_name,
        include_archived=include_archived,
        limit=limit,
    )


@router.get("/topics")
async def list_topics() -> list[dict[str, Any]]:
    return await get_personal_work_item_service().list_topics()


# IMPORTANT: declare the static /seed-va* paths BEFORE the dynamic /{task_id}
# capture, otherwise FastAPI may try to match the slug-style route first.
# Today they don't collide (path-segment counts differ), but explicit ordering
# is more durable as new routes get added.
@router.get("/seed-va/status")
async def va_seed_status():
    """Tell the UI whether VA tasks already exist (so it can hide the seed button)."""
    service = get_personal_work_item_service()
    existing = await service.list_work_items(topic=VA_TOPIC, limit=1, include_archived=True)
    return {"has_va_tasks": bool(existing), "topic": VA_TOPIC}


@router.post("/seed-va", response_model=SeedVAResponse)
async def seed_va(req: ActorRequest | None = None) -> SeedVAResponse:
    """Idempotently create the VA disability claim task tree.

    Skips items already present under the VA Claim topic, so running this twice
    is safe — useful for adding new seed items later.

    Identity is the ``guide:<anchor>`` tag, NOT the title. Titles get edited as
    the claim evolves (task #4 was retitled from "Request OMPF + Service
    Treatment Records" to reflect that the veteran holds the original STR), and
    a title-keyed seeder then treats the retitled task as missing and creates a
    duplicate. Title matching is retained only as a fallback for any seed item
    that has no guide anchor.
    """
    actor = req.actor if req else "user"
    service = get_personal_work_item_service()

    existing = await service.list_work_items(topic=VA_TOPIC, limit=1000, include_archived=True)
    existing_titles = {t.title.strip().lower() for t in existing}
    existing_anchors = {
        tag for t in existing for tag in (t.tags or []) if tag.startswith("guide:")
    }

    def _already_present(item: dict[str, Any]) -> bool:
        anchor = next(
            (tag for tag in item.get("tags", []) if tag.startswith("guide:")), None
        )
        if anchor:
            return anchor in existing_anchors
        return item["title"].strip().lower() in existing_titles

    created: list[Task] = []
    skipped = 0
    seed = _va_seed_tasks()
    for index, item in enumerate(seed):
        title = item["title"]
        if _already_present(item):
            skipped += 1
            continue
        payload = TaskCreate(
            title=title,
            description=item["description"],
            category=TaskCategory.CHORE,
            priority=item.get("priority", TaskPriority.MEDIUM),
            source=TaskSource.MANUAL,
            source_reference="va-disability-playbook-2026-05-12",
            domain=VA_TOPIC,
            owner_agent="self",
            tags=item.get("tags", []),
            links=item.get("links", []),
            sort_order=index + 1,
            risk_level="low",
            approval_state="none",
        )
        task = await service.create_work_item(payload, actor=actor)

        initial_status = item.get("status")
        if initial_status and initial_status != TaskStatus.BACKLOG:
            task = await service.update_work_item(
                task.id,
                TaskUpdate(status=initial_status),
                actor=actor,
            ) or task
        created.append(task)
        existing_titles.add(title.strip().lower())

    return SeedVAResponse(created=len(created), skipped=skipped, tasks=created)


@router.get("/{task_id}")
async def get_work_item(task_id: str):
    task = await get_personal_work_item_service().get_work_item(task_id)
    if not task:
        raise HTTPException(404, f"Personal work item {task_id} not found")
    return task


@router.get("/{task_id}/events")
async def events(task_id: str, limit: int = Query(default=200, ge=1, le=500)):
    task = await get_personal_work_item_service().get_work_item(task_id)
    if not task:
        raise HTTPException(404, f"Personal work item {task_id} not found")
    return await get_personal_work_item_service().events(task_id, limit=limit)


@router.post("")
async def create_work_item(task: TaskCreate):
    return await get_personal_work_item_service().create_work_item(task, actor="user")


@router.patch("/{task_id}")
async def update_work_item(task_id: str, updates: TaskUpdate):
    task = await get_personal_work_item_service().update_work_item(task_id, updates, actor="user")
    if not task:
        raise HTTPException(404, f"Personal work item {task_id} not found")
    return task


@router.post("/{task_id}/complete")
async def complete_work_item(task_id: str, req: CompleteRequest | None = None):
    request = req or CompleteRequest()
    task = await get_personal_work_item_service().complete_work_item(
        task_id, actor=request.actor, completion_note=request.completion_note
    )
    if not task:
        raise HTTPException(404, f"Personal work item {task_id} not found")
    return task


@router.delete("/{task_id}/notes/{event_id}")
async def delete_note(task_id: str, event_id: str):
    """Remove a note. Only event_type='note' rows are deletable so this
    cannot be abused to wipe audit history."""
    service = get_personal_work_item_service()
    ok = await service.delete_event(task_id, event_id)
    if not ok:
        raise HTTPException(404, "Note not found (or not a note)")
    return {"status": "deleted", "event_id": event_id}


@router.post("/{task_id}/notes")
async def add_note(task_id: str, req: NoteRequest):
    """Append a free-text note to a task. Stored as a company_task_events
    row with event_type='note' so it appears in the activity stream and the
    Notes panel filters them out by type."""
    service = get_personal_work_item_service()
    existing = await service.get_work_item(task_id)
    if not existing:
        raise HTTPException(404, f"Personal work item {task_id} not found")
    event = await service.record_event(
        task_id, "note", actor=req.actor, summary=req.note.strip(),
    )
    return event


@router.post("/{task_id}/reopen")
async def reopen_work_item(task_id: str, req: ActorRequest | None = None):
    task = await get_personal_work_item_service().reopen_work_item(
        task_id, actor=(req.actor if req else "user")
    )
    if not task:
        raise HTTPException(404, f"Personal work item {task_id} not found")
    return task


@router.delete("/{task_id}")
async def delete_work_item(task_id: str):
    deleted = await get_personal_work_item_service().delete_work_item(task_id, actor="user")
    if not deleted:
        raise HTTPException(404, f"Personal work item {task_id} not found")
    return {"status": "deleted", "task_id": task_id}


# -----------------------------------------------------------------------------
# Attachments — scans/photos/PDFs attached to a task (e.g. a DD-214 scan).
# Stored under the workspace volume so files survive a container rebuild
# (unlike backend/uploads/* used by the character-content uploader).
# -----------------------------------------------------------------------------

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
ALLOWED_ATTACHMENT_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/webp", "image/heic"}


@router.get("/{task_id}/attachments")
async def list_attachments(task_id: str):
    service = get_personal_work_item_service()
    if not await service.get_work_item(task_id):
        raise HTTPException(404, f"Personal work item {task_id} not found")
    return await service.list_attachments(task_id)


@router.post("/{task_id}/attachments")
async def upload_attachment(task_id: str, file: UploadFile = File(...)):
    service = get_personal_work_item_service()
    if not await service.get_work_item(task_id):
        raise HTTPException(404, f"Personal work item {task_id} not found")

    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_ATTACHMENT_TYPES:
        raise HTTPException(400, "Only PDF or image (jpeg/png/webp/heic) files are accepted")

    body = await file.read()
    if not body:
        raise HTTPException(400, "uploaded file is empty")
    if len(body) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(413, "file exceeds 10MB limit")

    ext_map = {
        "application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png",
        "image/webp": "webp", "image/heic": "heic",
    }
    ext = ext_map[content_type]
    dest_dir = get_workspace_path(f"personal/task_attachments/{task_id}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    dest_path = dest_dir / stored_name
    try:
        dest_path.write_bytes(body)
    except OSError:
        raise HTTPException(500, "failed to persist uploaded file")

    return await service.create_attachment(
        task_id,
        filename=file.filename or stored_name,
        content_type=content_type,
        size_bytes=len(body),
        storage_path=str(dest_path),
        actor="user",
    )


@router.delete("/{task_id}/attachments/{attachment_id}")
async def delete_attachment(task_id: str, attachment_id: str):
    service = get_personal_work_item_service()
    ok = await service.delete_attachment(task_id, attachment_id, actor="user")
    if not ok:
        raise HTTPException(404, "Attachment not found")
    return {"status": "deleted", "attachment_id": attachment_id}


# Separate router: browsers can't set an Authorization header on <a href>/<img>
# tags, so this file-serving endpoint accepts ?token= as well (require_auth_flex),
# same convention as character_reference_videos.file_router.
file_router = APIRouter(
    prefix="/api/personal/work-items",
    tags=["personal-work-items"],
    dependencies=[Depends(require_auth_flex)],
)


@file_router.get("/{task_id}/attachments/{attachment_id}/file")
async def serve_attachment(task_id: str, attachment_id: str):
    service = get_personal_work_item_service()
    row = await service.get_attachment(task_id, attachment_id)
    if not row:
        raise HTTPException(404, "Attachment not found")
    path = _Path(row.storage_path)
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "Attachment file missing on disk")
    return FileResponse(
        path=str(path),
        media_type=row.content_type,
        filename=row.filename,
    )


# -----------------------------------------------------------------------------
# VA Claim seed — handlers are declared up top (before /{task_id})
# so FastAPI route ordering stays unambiguous. Only the seed data lives here.
# -----------------------------------------------------------------------------


def _va_seed_tasks() -> list[dict[str, Any]]:
    """Return the canonical VA disability seed.

    Order matters — sort_order is assigned by index. Phase encoded in tags so
    the UI can group by phase ("phase:7d", "phase:30d", ...).
    """
    # ---- Phase: TL;DR + reference --------------------------------------------------
    items: list[dict[str, Any]] = [
        {
            "title": "VA Claim Playbook — TL;DR + strategy summary",
            "description": (
                "**One-page summary of the full playbook. Keep this pinned.**\n\n"
                "**Strategy:** File a single, consolidated Intent to File (VA Form 21-0966) today to lock in the effective date, then submit a Fully Developed Claim (FDC) bundling:\n"
                "  (1) GERD / hiatal hernia / post-fundoplication dysphagia as one direct-service-connection chain anchored to the in-service INH prescription and Nissen fundoplication,\n"
                "  (2) generalized anxiety disorder as secondary to that GI chain under 38 C.F.R. § 3.310, and\n"
                "  (3) tinnitus as direct service connection (Navy AE = 'Highly Probable' noise exposure per VBA Fast Letter 10-35).\n\n"
                "**Realistic combined-rating estimate: 50%–70%** (~$1,132.90–$1,808.45/month at 2026 single-veteran rates).\n\n"
                "**Free help first, paid help only on appeal.** Start with Duval CVSO ((904) 255-5550) or DAV. Hire a VA-accredited attorney (CCK / Hill & Ponton / Berry Law) only if the initial decision underrates him — under 38 U.S.C. § 5904 attorneys cannot legally charge for initial claims.\n\n"
                "**Single biggest rating lever:** documented esophageal stricture or dilatation. Get an EGD or barium swallow BEFORE the C&P exam — that one line item moves the GI rating from 10% → 30% → 50% under DC 7206.\n\n"
                "---\n"
                "**Verify all VSOs/attorneys at https://www.va.gov/ogc/apps/accreditation/ before signing a VA Form 21-22 power of attorney.**\n"
            ),
            "priority": TaskPriority.HIGH,
            "status": TaskStatus.IN_PROGRESS,
            "tags": ["phase:reference", "pinned", "guide:strategy"],
            "links": [
                {"label": "VA accreditation search", "url": "https://www.va.gov/ogc/apps/accreditation/"},
                {"label": "VA.gov", "url": "https://www.va.gov"},
            ],
        },
        # ---- Phase: 7 days -----------------------------------------------------------
        {
            "title": "File Intent to File (VA Form 21-0966) — TODAY",
            "description": (
                "**Single most time-sensitive action in the entire playbook.** Filing the ITF locks in today's date as the effective date for ALL conditions; under 38 C.F.R. § 3.155(b) any complete claim filed within 365 days back-dates to today.\n\n"
                "**Three filing methods (pick one — online is fastest):**\n"
                "1. **Online** — https://www.va.gov/resources/your-intent-to-file-a-va-claim/ — auto-creates ITF when you start a Form 21-526EZ.\n"
                "2. **Phone** — 1-800-827-1000.\n"
                "3. **Mail** — VA Form 21-0966, certified mail with return receipt.\n\n"
                "**Cover all three conditions on the form:**\n"
                "  - Compensation — GERD / hiatal hernia / post-fundoplication residuals\n"
                "  - Compensation — Generalized anxiety disorder (secondary)\n"
                "  - Compensation — Tinnitus\n\n"
                "**Save the confirmation number / receipt.** Attach as completion evidence."
            ),
            "priority": TaskPriority.CRITICAL,
            "status": TaskStatus.TODO,
            "tags": ["phase:7d", "action:filing", "guide:intent-to-file"],
            "links": [
                {"label": "File ITF online", "url": "https://www.va.gov/resources/your-intent-to-file-a-va-claim/"},
                {"label": "Form 21-0966 PDF", "url": "https://www.vba.va.gov/pubs/forms/VBA-21-0966-ARE.pdf"},
            ],
        },
        {
            "title": "Create digital accounts (VA.gov / MyHealtheVet / milConnect / eVetRecs)",
            "description": (
                "Establish the four federal accounts you'll need to pull records, file the claim, and read decision letters.\n\n"
                "**1. VA.gov** — https://www.va.gov — use Login.gov or ID.me identity verification (same-day).\n"
                "**2. MyHealtheVet** — https://www.myhealth.va.gov — Blue Button download of VA medical records.\n"
                "**3. milConnect (DPRIS)** — https://milconnect.dmdc.osd.mil — fastest path to DD-214 and STRs for post-1995 Navy service. Path: Correspondence/Documentation → DPRIS → Personnel File.\n"
                "**4. eVetRecs (NARA)** — https://vetrecs.archives.gov — backup path for OMPF and STRs (2–4 weeks standard, 1–5 days emergency).\n\n"
                "Use the same email address across all four so VA can match identity. Save credentials to your password manager."
            ),
            "priority": TaskPriority.HIGH,
            "status": TaskStatus.TODO,
            "tags": ["phase:7d", "action:accounts", "guide:digital-accounts"],
            "links": [
                {"label": "VA.gov", "url": "https://www.va.gov"},
                {"label": "MyHealtheVet", "url": "https://www.myhealth.va.gov"},
                {"label": "milConnect", "url": "https://milconnect.dmdc.osd.mil"},
                {"label": "eVetRecs", "url": "https://vetrecs.archives.gov"},
            ],
        },
        {
            "title": "Request OMPF + Service Treatment Records (STRs)",
            "description": (
                "**Why these matter:** STRs contain the in-service INH prescription, hiatal hernia workup, pre-op clearance, surgical report ('laparoscopic Nissen fundoplication'; CPT 43280 if listed), and post-op follow-ups. These records establish the 'in-service event' prong of direct service connection under 38 C.F.R. § 3.303.\n\n"
                "**Primary path (fastest):**\n"
                "  - milConnect DPRIS → Correspondence/Documentation → DPRIS → Personnel File (days–weeks for post-Jan 1, 1995 Navy)\n\n"
                "**Backup paths:**\n"
                "  - NARA eVetRecs → https://vetrecs.archives.gov (2–4 weeks standard; 1–5 days emergency)\n"
                "  - SF-180 mail/fax: NPRC, 1 Archives Drive, St. Louis, MO 63138 / Fax 314-801-9195 (4–8 weeks)\n"
                "  - Navy Personnel Command (PERS-313), 5720 Integrity Drive, Millington, TN 38055\n\n"
                "**What to look for in the records once received:**\n"
                "  - Date and provider of INH prescription\n"
                "  - Date(s) of hiatal hernia workup (upper GI series, EGD, manometry)\n"
                "  - Operative report for the Nissen fundoplication (surgeon, hospital, date)\n"
                "  - All post-op follow-up notes documenting reflux/dysphagia\n"
                "  - DD-214 confirming AE rating (for tinnitus)\n\n"
                "Upload to a secure folder; you'll attach these as evidence to the 21-526EZ."
            ),
            "priority": TaskPriority.HIGH,
            "status": TaskStatus.TODO,
            "tags": ["phase:7d", "action:records", "guide:ompf-strs"],
            "links": [
                {"label": "milConnect", "url": "https://milconnect.dmdc.osd.mil"},
                {"label": "eVetRecs", "url": "https://vetrecs.archives.gov"},
                {"label": "NARA SF-180", "url": "https://www.archives.gov/veterans/military-service-records"},
            ],
        },
        {
            "title": "Apply for VA health care (PACT-era eligibility)",
            "description": (
                "Separate from disability comp. Enrollment is free and unlocks toxic-exposure screening + access to VA GI clinic (which can pull the EGD that drives the rating up).\n\n"
                "**Apply:** https://www.va.gov/health-care/apply/\n\n"
                "**Why apply now even though PACT doesn't directly cover GERD:**\n"
                "  - PACT-era enrollment is automatic for any service in burn-pit/toxic-exposure locations (Bahrain, Iraq, Kuwait, Oman, Qatar, Saudi Arabia, Afghanistan, Djibouti, etc.) on/after Aug 2, 1990 or Sept 11, 2001.\n"
                "  - Enrollment opens the door to VA GI specialists who can do the EGD that documents stricture/dilatation — the single biggest lever for the GI rating.\n"
                "  - Sets up future presumptive eligibility if any of the 20+ PACT-listed cancers/respiratory conditions develop.\n\n"
                "Bring DD-214 (or order one via milConnect)."
            ),
            "priority": TaskPriority.HIGH,
            "status": TaskStatus.TODO,
            "tags": ["phase:7d", "action:healthcare", "guide:va-health-care"],
            "links": [
                {"label": "Apply for VA health care", "url": "https://www.va.gov/health-care/apply/"},
            ],
        },
        # ---- Phase: 30 days ----------------------------------------------------------
        {
            "title": "Appointment with Duval CVSO (or DAV) — sign VA Form 21-22 (POA)",
            "description": (
                "**Free, federally accredited help. Do this BEFORE hiring any paid attorney — attorneys cannot legally charge for initial claims under 38 U.S.C. § 5904.**\n\n"
                "**Top local choice — Duval CVSO:**\n"
                "  - City of Jacksonville Military Affairs & Veterans Department (MAVD)\n"
                "  - 117 W. Duval St., Suite 175, Jacksonville, FL 32202\n"
                "  - **(904) 255-5550** | vetsvcs@coj.net\n"
                "  - Mon–Fri 7:00 AM – 3:00 PM (walk-ins; appointments preferred)\n"
                "  - Supervisor: Rafael Santiago; Senior VSOs: Travis Sims, Fred Berley, Manuel DeGuzman, J. Daniel McKinney III, Jacqueline Harris\n\n"
                "**National backups:**\n"
                "  - DAV — https://www.dav.org/find-your-local-office/\n"
                "  - American Legion — https://www.legion.org/serviceofficers\n"
                "  - VFW Post 3270 (Jax Beach), (904) 249-7366, vfw3270vso@gmail.com\n\n"
                "**Verify accreditation at https://www.va.gov/ogc/apps/accreditation/ before signing the POA.**\n\n"
                "**At the appointment:** sign VA Form 21-22 power of attorney; ask for FDC certification; ask if a Decision Ready Claim (DRC) is feasible (often <30 days)."
            ),
            "priority": TaskPriority.HIGH,
            "status": TaskStatus.TODO,
            "tags": ["phase:30d", "action:vso", "guide:cvso-poa"],
            "links": [
                {"label": "VA accreditation search", "url": "https://www.va.gov/ogc/apps/accreditation/"},
                {"label": "Duval CVSO", "url": "https://www.coj.net/departments/military-affairs-and-veterans-department"},
                {"label": "DAV office locator", "url": "https://www.dav.org/find-your-local-office/"},
            ],
        },
        {
            "title": "Schedule GI consult + EGD or barium swallow — RATING LEVER",
            "description": (
                "**This is the single biggest move you can make to raise the GI rating.**\n\n"
                "**Why it matters:** Under the new DC 7206 (effective May 19, 2024, 89 Fed. Reg. 19743), the rating ladder is keyed to documented esophageal stricture/dilatation:\n"
                "  - 0% — documented history without daily symptoms or daily medication\n"
                "  - 10% — stricture requiring daily medication to control dysphagia, otherwise asymptomatic\n"
                "  - 30% — recurrent stricture requiring dilatation **no more than 2 times per year**\n"
                "  - 50% — recurrent or refractory stricture requiring dilatation **3 or more times per year**, OR steroid-assisted dilatation at least once a year, OR stent placement\n"
                "  - 80% — recurrent/refractory stricture causing dysphagia with aspiration, undernutrition, and/or substantial weight loss, plus surgical correction or PEG\n\n"
                "**CORRECTED 2026-08-03 — the earlier version of this ladder had 30% and 50% swapped.** "
                "**More frequent dilatation supports a HIGHER rating, not a lower one.** Every dilatation, every steroid-assisted procedure, and every food impaction requiring intervention must be in the record with a date — do NOT under-report frequency at the C&P exam. Verified against 38 C.F.R. 4.114 (DC 7206 rates by reference to DC 7203).\n\n"
                "**Without an EGD on record, the rater can default to 10%** no matter how severe the symptoms are.\n\n"
                "**Action:** Get a GI consult through VA (once VA health care is approved) OR a private gastroenterologist. Ask specifically for:\n"
                "  - Upper endoscopy (EGD) with biopsies\n"
                "  - Barium swallow (esophagram) if dysphagia is prominent\n"
                "  - Esophageal manometry if motility issues suspected\n\n"
                "**Bring this list to the consult:** nightly heartburn, daily PPI dose, dysphagia episodes, food impactions, regurgitation, sleep disruption, chest pain after meals. Document EVERY symptom — that becomes the C&P examiner's roadmap."
            ),
            "priority": TaskPriority.HIGH,
            "status": TaskStatus.TODO,
            "tags": ["phase:30d", "action:medical", "rating-lever", "guide:gi-consult"],
            "links": [],
        },
        {
            "title": "Gather buddy statements (VA Form 21-10210)",
            "description": (
                "Lay statements from people who personally observed your in-service or current symptoms. **These count as evidence under 38 C.F.R. § 3.159(a)(2).**\n\n"
                "**Best candidates to ask:**\n"
                "  - Spouse — current symptoms (nightly reflux, sleep disruption, food avoidance, anxiety)\n"
                "  - Family member — symptom continuity since separation\n"
                "  - Former shipmate(s) from same squadron — in-service INH treatment, flight-line noise exposure, observed stomach problems\n"
                "  - Anyone present at meals where you struggled to swallow\n\n"
                "**Template (sign under penalty of perjury):**\n"
                "> 'I, [Name], being duly sworn, state: I have known [Adam] since [year/relationship]. I served with him aboard [ship/squadron] from [dates] / I am his spouse and have lived with him since [date]. I personally observed [specific symptom — e.g., him taking isoniazid in [year] and complaining of severe heartburn / him struggling with nightly heartburn that wakes him up / him describing constant ringing in his ears after flight-line work on [aircraft type]]. These symptoms have been continuous.\n"
                ">\n"
                "> I declare under penalty of perjury under the laws of the United States that the foregoing is true and correct. Executed on [date]. [Signature]'\n\n"
                "Aim for **3 statements total**: one spouse, one family, one shipmate. Save signed PDFs to the evidence folder."
            ),
            "priority": TaskPriority.MEDIUM,
            "status": TaskStatus.TODO,
            "tags": ["phase:30d", "action:evidence", "guide:buddy-statements"],
            "links": [
                {"label": "Form 21-10210 PDF", "url": "https://www.vba.va.gov/pubs/forms/VBA-21-10210-ARE.pdf"},
            ],
        },
        {
            "title": "Draft personal statement (VA Form 21-4138)",
            "description": (
                "Your own first-person narrative covering all three conditions. A strong personal statement frames the entire claim for the rater.\n\n"
                "**Three sections to write:**\n"
                "  1. **GI chain** — onset, INH prescription, Nissen fundoplication, current daily symptoms (heartburn, dysphagia, regurgitation, sleep disruption, foods avoided, medications and doses, chest/shoulder pain).\n"
                "  2. **Anxiety secondary** — quantify panic attacks per week, sleep impact, social/work avoidance, medications, no pre-service history.\n"
                "  3. **Tinnitus** — AE duties, specific aircraft, noise exposure (engine run-ups, flight line), onset in service, current frequency, sleep/concentration impact.\n\n"
                "**Use the draft in the playbook (Section H) as your starting point** — edit bracketed placeholders to specifics. Reference it in the linked narrative tasks (GERD / Anxiety / Tinnitus) which serve as living docs you'll refine over time.\n\n"
                "**Tone:** describe the worst day, not the best. Specific > general. Include dates and durations. Sign under penalty of perjury."
            ),
            "priority": TaskPriority.MEDIUM,
            "status": TaskStatus.TODO,
            "tags": ["phase:30d", "action:evidence", "guide:personal-statement"],
            "links": [
                {"label": "Form 21-4138 PDF", "url": "https://www.vba.va.gov/pubs/forms/VBA-21-4138-ARE.pdf"},
            ],
        },
        # ---- Phase: 60 days ----------------------------------------------------------
        {
            "title": "Assemble medical evidence packet (STRs + current records)",
            "description": (
                "By day 60 you should have STRs in hand. Build a single PDF packet for the claim.\n\n"
                "**Required in the packet:**\n"
                "  - DD-214 (front and back)\n"
                "  - OMPF excerpts confirming AE rating\n"
                "  - In-service INH prescription record (look for it in pharmacy logs or sick-call entries)\n"
                "  - Operative report for Nissen fundoplication\n"
                "  - All post-op follow-up notes\n"
                "  - Current GI records (last 12 months minimum) — EGD report, barium swallow, manometry, medication list\n"
                "  - Mental health records — diagnoses, prescriptions, treatment notes\n"
                "  - Audiology records if any (for tinnitus)\n\n"
                "**Organization:** chronological within each condition. Tab or bookmark each major section. Number every page. This is what gets uploaded with the 21-526EZ."
            ),
            "priority": TaskPriority.HIGH,
            "status": TaskStatus.BACKLOG,
            "tags": ["phase:60d", "action:evidence", "guide:evidence-packet"],
            "links": [],
        },
        {
            "title": "Obtain GI nexus letter from private specialist",
            "description": (
                "**The single most persuasive document in the GI claim.** A nexus letter ties current diagnoses to in-service events using the magic phrase 'at least as likely as not (≥50% probability).'\n\n"
                "**Who to ask:** Your treating GI specialist is ideal (already knows your case). Backup: a contracted independent medical examiner (IME). Budget $400–$2,000 for an IME if needed.\n\n"
                "**Required elements (on clinician letterhead, signed):**\n"
                "  1. Credentials (license, board cert, years practicing)\n"
                "  2. Records reviewed (STRs, INH prescription record, op report, current charts)\n"
                "  3. Current diagnoses (GERD, post-fundoplication dysphagia, post-surgical residuals)\n"
                "  4. **The Opinion line:** 'It is at least as likely as not (50% probability or greater) that Mr. Doherty's current GERD, dysphagia, and post-fundoplication residuals were caused by, or in the alternative aggravated beyond their natural progression by, his in-service prescription of isoniazid and the in-service laparoscopic Nissen fundoplication.'\n"
                "  5. **Rationale citing literature:**\n"
                "     - INH labeling + StatPearls (Badrinath et al., 2024) — heartburn, nausea, GI upset are common adverse effects\n"
                "     - Cleveland Clinic / Stanford Health / PMID 12409696 (Surg Endosc) / ACG 2024 — long-term post-Nissen complications include persistent dysphagia (up to 25%), gas-bloat, recurrent GERD\n"
                "     - **Mittleider v. West, 11 Vet. App. 181 (1998)** — when an examiner can't separate medication-induced aggravation from baseline, all symptoms are attributed to service\n"
                "     - Persuasive BVA cases: 0916857, 1736521, 0310420 (NSAID-induced GERD analogues)\n"
                "  6. Signature, credentials, license number, date\n\n"
                "Full template is in the playbook (Section C.4) — share it with the clinician."
            ),
            "priority": TaskPriority.HIGH,
            "status": TaskStatus.BACKLOG,
            "tags": ["phase:60d", "action:nexus", "guide:gi-nexus"],
            "links": [],
        },
        {
            "title": "Anxiety treatment records + nexus paragraph from prescriber",
            "description": (
                "For the secondary anxiety claim under 38 C.F.R. § 3.310.\n\n"
                "**What to collect:**\n"
                "  - Treatment notes from prescriber (psychiatrist / PCP) showing diagnosis, severity, frequency of panic attacks\n"
                "  - Medication list with dosages and start dates\n"
                "  - Any prior mental health records (to show no pre-service anxiety history)\n\n"
                "**Ask the prescriber for a short opinion paragraph:**\n"
                "> 'In my clinical opinion, it is at least as likely as not that Mr. Doherty's generalized anxiety disorder is secondary to and aggravated by his chronic gastrointestinal condition (GERD, post-Nissen fundoplication dysphagia). The literature (Menon et al., Am J Gastroenterol 108:S571, 2013; Gradus et al., Epidemiology 28:354, 2017) supports a significant association between chronic GI illness and anxiety. Mr. Doherty's symptom timeline — anxiety onset following the GI surgery, no pre-service mental health history — is consistent with this established pattern.'\n\n"
                "This paragraph is shorter and easier to get than the GI nexus letter — most PCPs will write it during a routine visit."
            ),
            "priority": TaskPriority.MEDIUM,
            "status": TaskStatus.BACKLOG,
            "tags": ["phase:60d", "action:nexus", "guide:anxiety-nexus"],
            "links": [],
        },
        {
            "title": "Verify AE rating in DD-214/OMPF for tinnitus claim",
            "description": (
                "Tinnitus at 10% is essentially automatic for a Navy AE — but only if the AE rating is documented.\n\n"
                "**Why it's near-automatic:**\n"
                "  - VBA Duty MOS Noise Exposure Listing (Fast Letter 10-35, Sept. 2010): **'71 AE AVIATION ELECTRICIANS MATE — X [Highly Probable]'**\n"
                "  - Every Navy 'Aviation' rating (AB, ABE, ABF, ABH, AC, AD, AE, AM, AME, AO, AS, AT, AW) carries the 'Highly Probable' designation\n"
                "  - Under M21-1, V.iii.2.B.3.b a separate medical opinion is not always required when the veteran provides a credible lay statement\n"
                "  - 38 C.F.R. § 4.87, DC 6260 = flat 10%\n\n"
                "**Action:** Confirm DD-214 line 12 (rating at separation) shows AE. If it shows a different rating with AE as cross-trained, pull the OMPF page showing the AE designation. Save as evidence."
            ),
            "priority": TaskPriority.LOW,
            "status": TaskStatus.BACKLOG,
            "tags": ["phase:60d", "action:evidence", "condition:tinnitus", "guide:ae-rating"],
            "links": [],
        },
        # ---- Phase: 90 days ----------------------------------------------------------
        {
            "title": "Submit VA Form 21-526EZ as Fully Developed Claim (FDC)",
            "description": (
                "**The big filing.** Once all evidence is gathered (STRs, current records, nexus letter, buddy statements, personal statement), submit through the VSO.\n\n"
                "**Why FDC over Standard:**\n"
                "  - FDC: ~75.7 days average (per VA.gov April 2026 tracker)\n"
                "  - Standard: VA gathers evidence for you (slower, less control)\n"
                "  - DRC through VSO: often ≤30 days\n\n"
                "**On the form, claim all three conditions:**\n"
                "  1. GERD / hiatal hernia / post-laparoscopic Nissen fundoplication residuals (direct service connection)\n"
                "  2. Generalized anxiety disorder, secondary to GI condition (38 C.F.R. § 3.310)\n"
                "  3. Tinnitus (direct service connection, AE noise exposure)\n\n"
                "**Attach:**\n"
                "  - Medical evidence packet\n"
                "  - GI nexus letter\n"
                "  - Anxiety nexus paragraph\n"
                "  - Buddy statements (Form 21-10210)\n"
                "  - Personal statement (Form 21-4138)\n"
                "  - DD-214\n\n"
                "**Sign and submit through the CVSO/DAV** — they'll certify the FDC and route it. Get a confirmation receipt with the claim number."
            ),
            "priority": TaskPriority.CRITICAL,
            "status": TaskStatus.BACKLOG,
            "tags": ["phase:90d", "action:filing", "guide:form-526ez"],
            "links": [
                {"label": "Form 21-526EZ PDF", "url": "https://www.vba.va.gov/pubs/forms/VBA-21-526EZ-ARE.pdf"},
            ],
        },
        {
            "title": "Prepare for three C&P exams (GI / Mental Health / Audio)",
            "description": (
                "C&P exams are typically scheduled 3–8 weeks after claim receipt. Three separate exams.\n\n"
                "**Universal rules:**\n"
                "  - SHOW UP. Missing a C&P is the fastest way to be denied.\n"
                "  - Describe your worst day, not your best. If asked 'How are you?', do not answer 'I'm fine.'\n"
                "  - Bring a written symptom log to every exam.\n\n"
                "**Esophageal Conditions DBQ:**\n"
                "  - Mention daily PPI dose, post-Nissen dysphagia, food impactions, regurgitation, sleep disruption, chest pain\n"
                "  - **Name every dilatation by date and provider** — single line item moves rating 10% → 30% → 50%\n\n"
                "**Mental Disorders DBQ:**\n"
                "  - Quantify panic attacks per week (e.g., '2–3')\n"
                "  - Sleep disruption hours, social isolation, work concentration impact, missed workdays\n"
                "  - No pre-service mental health history\n\n"
                "**Hearing Loss & Tinnitus DBQ:**\n"
                "  - Sound type (ringing, buzzing, hissing), constant vs. intermittent\n"
                "  - Sleep/concentration impact\n"
                "  - Link to AE flight-line noise exposure — name specific aircraft and squadron\n\n"
                "All DBQs visible at https://www.benefits.va.gov/compensation/dbq_publicdbqs.asp"
            ),
            "priority": TaskPriority.HIGH,
            "status": TaskStatus.BACKLOG,
            "tags": ["phase:90d", "action:exam", "guide:cp-exams"],
            "links": [
                {"label": "Public DBQs", "url": "https://www.benefits.va.gov/compensation/dbq_publicdbqs.asp"},
            ],
        },
        {
            "title": "Build written symptom log for C&P exams",
            "description": (
                "A 1-page log brought to every C&P exam. Examiners often capture exactly what's on the log — so write the truth, vividly.\n\n"
                "**Format — one section per condition:**\n\n"
                "**GI section:**\n"
                "  - Daily PPI: [drug, dose, frequency]\n"
                "  - Reflux episodes per day/week\n"
                "  - Nights waking from heartburn per week\n"
                "  - Foods avoided (specific list)\n"
                "  - Dysphagia episodes per week — solids vs. liquids\n"
                "  - Food impactions in last 12 months (count + dates if known)\n"
                "  - Regurgitation episodes per week\n"
                "  - Chest/shoulder pain after meals — frequency, severity 1–10\n"
                "  - Weight loss, if any\n"
                "  - Dilatation history — dates, provider, procedure\n\n"
                "**Anxiety section:**\n"
                "  - Panic attacks per week (count)\n"
                "  - Sleep: hours, quality, awakenings\n"
                "  - Social avoidance: restaurants, family events, work meetings\n"
                "  - Concentration: missed deadlines, work errors\n"
                "  - Missed workdays per month\n"
                "  - Medications: list with start dates\n\n"
                "**Tinnitus section:**\n"
                "  - Sound type, pitch, constant vs. intermittent\n"
                "  - Hours per day perceived\n"
                "  - Sleep impact: nights affected per week\n"
                "  - Concentration impact in quiet environments\n"
                "  - Onset relative to AE service\n\n"
                "Print 3 copies — one per exam."
            ),
            "priority": TaskPriority.MEDIUM,
            "status": TaskStatus.BACKLOG,
            "tags": ["phase:90d", "action:exam", "guide:symptom-log"],
            "links": [],
        },
        # ---- Phase: Reference — narrative / living docs --------------------------------
        {
            "title": "Narrative — GERD / Hiatal Hernia / Post-Nissen (LIVING DOC)",
            "description": (
                "**This task's description IS the narrative. Edit it over time as memory and records sharpen.** Each save creates an audit-trail event so you can see how the narrative evolved.\n\n"
                "---\n\n"
                "**Current narrative (v0 — draft):**\n\n"
                "In approximately [YEAR], while assigned to [SHIP/SQUADRON/STATION], I began experiencing severe heartburn and stomach pain. I was evaluated at [MEDICAL FACILITY — e.g., NAS Jacksonville Branch Medical Clinic], and a hiatal hernia was diagnosed/suspected. The Navy also prescribed me **isoniazid (INH)** for [tuberculosis prophylaxis / a positive PPD]. After starting INH, my stomach symptoms became significantly worse — severe heartburn, nausea, and difficulty keeping food down. I reported the worsening to [DR./CORPSMAN NAME if known].\n\n"
                "On approximately [DATE] I underwent a **laparoscopic Nissen fundoplication** at [HOSPITAL — e.g., Naval Hospital Jacksonville]. The surgeon wrapped the top of my stomach around the bottom of my esophagus to tighten it and stop the reflux. I returned to duty after [RECOVERY PERIOD].\n\n"
                "Since the surgery I have never been the same. I experience:\n"
                "  - Nightly heartburn that wakes me up; I sleep with [X PILLOWS / a wedge]\n"
                "  - Difficulty swallowing food, especially solids — food sometimes gets stuck and I have to drink water or regurgitate\n"
                "  - Daily reflux despite [MEDICATION — e.g., omeprazole 40 mg twice daily]\n"
                "  - Bloating, inability to belch normally, gas pain\n"
                "  - Chest and shoulder pain after meals\n"
                "  - I avoid [LIST TRIGGER FOODS]\n\n"
                "My condition has progressively worsened. My current provider has told me I will have to live with this for the rest of my life.\n\n"
                "---\n\n"
                "**TODO — fill in:**\n"
                "  - Year(s) of onset and INH prescription\n"
                "  - Specific ship/squadron names and dates\n"
                "  - Naming providers from STRs once received\n"
                "  - Exact date of Nissen fundoplication\n"
                "  - Current medications and doses\n"
                "  - List of foods you avoid\n"
                "  - Specific sleep accommodations\n"
                "  - Any dilatation history (this is the rating lever)\n"
            ),
            "priority": TaskPriority.HIGH,
            "status": TaskStatus.IN_PROGRESS,
            "tags": ["phase:reference", "narrative", "condition:gi", "pinned", "guide:narrative-gerd"],
            "links": [],
        },
        {
            "title": "Narrative — Anxiety secondary to GI chain (LIVING DOC)",
            "description": (
                "**Edit this description over time. Each save creates an audit-trail event.**\n\n"
                "---\n\n"
                "**Current narrative (v0 — draft):**\n\n"
                "Living with chronic daily GI symptoms — never knowing when food will get stuck, waking up at night choking on reflux, embarrassment at meals — has caused me significant and worsening anxiety.\n\n"
                "I am currently prescribed [LIST MEDICATIONS — drug, dose, prescriber] by [PROVIDER NAME, CLINIC].\n\n"
                "I experience:\n"
                "  - Panic attacks approximately [X] times per week\n"
                "  - Chronic sleep disturbance — wake [X] times per night on average\n"
                "  - Avoidance of restaurants and social meals\n"
                "  - Difficulty concentrating at work\n"
                "  - [MISSED WORKDAYS per month, if applicable]\n\n"
                "I had no history of anxiety prior to the onset of my GI condition.\n\n"
                "---\n\n"
                "**Legal basis for secondary service connection:**\n"
                "  - 38 C.F.R. § 3.310(a) — 'disability which is proximately due to or the result of a service-connected disease or injury shall be service connected'\n"
                "  - § 3.310(b) covers aggravation\n"
                "  - Menon et al., Am J Gastroenterol 108:S571 (2013) — veterans with chronic GI illness have higher rates of anxiety/depression\n"
                "  - Gradus et al., Epidemiology 28:354 (2017) — Danish population cohort confirmed PTSD/anxiety ↔ GI association\n\n"
                "---\n\n"
                "**TODO — fill in:**\n"
                "  - Current medications and prescriber name\n"
                "  - Quantified panic attack frequency\n"
                "  - Sleep disturbance specifics\n"
                "  - Concrete examples of social/work avoidance\n"
                "  - Onset timeline relative to GI surgery\n"
            ),
            "priority": TaskPriority.HIGH,
            "status": TaskStatus.IN_PROGRESS,
            "tags": ["phase:reference", "narrative", "condition:anxiety", "pinned", "guide:narrative-anxiety"],
            "links": [],
        },
        {
            "title": "Narrative — Tinnitus (Navy AE noise exposure) (LIVING DOC)",
            "description": (
                "**Edit this description over time. Each save creates an audit-trail event.**\n\n"
                "---\n\n"
                "**Current narrative (v0 — draft):**\n\n"
                "As an Aviation Electrician's Mate (AE), my duties included [SPECIFIC TASKS — e.g., troubleshooting and repairing electrical systems on F/A-18 / P-3 / SH-60 aircraft / working the flight line / participating in engine run-ups and turn-ups].\n\n"
                "I was exposed to high-intensity jet engine noise on a near-daily basis during my time at [SQUADRON(S) / NAS JACKSONVILLE / NAS MAYPORT / ABOARD USS [NAME]]. Hearing protection was provided but was inadequate during [SPECIFIC SITUATIONS — e.g., emergency tarmac responses, intercom communications, close-proximity engine work].\n\n"
                "I began noticing ringing in my ears during my service and the ringing has continued since separation. It is [CONSTANT / INTERMITTENT], [DESCRIBE — e.g., high-pitched ringing, hissing, buzzing], and it interferes with my sleep and ability to concentrate in quiet environments.\n\n"
                "---\n\n"
                "**Why this claim is near-automatic for AE:**\n"
                "  - VBA Duty MOS Noise Exposure Listing (Fast Letter 10-35): AE = 'X [Highly Probable]'\n"
                "  - VA must concede in-service noise exposure\n"
                "  - M21-1, V.iii.2.B.3.b — separate medical opinion not always required when veteran provides credible lay statement\n"
                "  - M21-1, V.iii.12.A.1.d — tinnitus classified as 'organic disease of the nervous system,' eligible for continuity-of-symptomatology service connection under §§ 3.307, 3.309(a)\n"
                "  - 38 C.F.R. § 4.87, DC 6260 = flat 10% (no higher rating possible under current rule)\n\n"
                "---\n\n"
                "**TODO — fill in:**\n"
                "  - Specific aircraft types worked on\n"
                "  - Specific squadrons + dates\n"
                "  - Onset timeline (during/after which deployment or evolution)\n"
                "  - Sound character (pitch, constant vs. intermittent)\n"
                "  - Concrete sleep/concentration impact examples\n"
            ),
            "priority": TaskPriority.HIGH,
            "status": TaskStatus.IN_PROGRESS,
            "tags": ["phase:reference", "narrative", "condition:tinnitus", "pinned", "guide:narrative-tinnitus"],
            "links": [],
        },
        {
            "title": "Rating estimate tracker — Conservative / Likely / Strong scenarios",
            "description": (
                "**Use this to track which scenario you're tracking toward as evidence comes in.**\n\n"
                "**38 C.F.R. § 4.25 combined rating math (whole-person rule, largest first):**\n\n"
                "The rating is **100 minus remaining efficiency**, rounded to the nearest 10 ONCE, at the very end. "
                "An earlier version of this tracker reported remaining efficiency as if it were the rating, which understated every scenario by a full bracket.\n\n"
                "| Scenario | GERD | Anxiety | Migraine | Tinnitus | Hearing | Scars | Combined | 2026 monthly (single, no deps) |\n"
                "|---|---|---|---|---|---|---|---|---|\n"
                "| Conservative | 10% | 30% | 0% | 10% | 0% | 0% | **40%** | $795.84 |\n"
                "| **Likely** | **30%** | **30%** | **30%** | **10%** | 0% | **10%** | **70%** | **$1,808.45** |\n"
                "| Strong | 50% | 50% | 30% | 10% | 10% | 10% | **90%** | $2,362.30 |\n\n"
                "**Worked example (Likely):** largest first — 30, 30, 30, 10, 10.\n"
                "  - 30% leaves 70 efficient\n"
                "  - 30% of 70 = 21 → 49 efficient\n"
                "  - 30% of 49 = 14.7 → 34.3 efficient\n"
                "  - 10% of 34.3 = 3.43 → 30.87 efficient\n"
                "  - 10% of 30.87 = 3.09 → 27.78 efficient\n"
                "  - Combined = 100 − 27.78 = 72.2 → rounds to **70%**\n\n"
                "**What the added conditions are worth.** The original three-condition claim (GERD + anxiety + tinnitus) tops out at 60% Likely / 80% Strong. "
                "Adding migraines and surgical scars moves Likely to 70% — $1,435.02 → $1,808.45, about **$373/month**. Hearing loss frequently rates 0%, but a 0% rating still establishes service connection, which turns any future worsening into a simple increase rather than a fresh claim.\n\n"
                "---\n\n"
                "**2026 VA compensation rates (single veteran, no dependents)** — effective Dec. 1, 2025, reflecting the 2.8% COLA:\n\n"
                "| Rating | Monthly |\n"
                "|---|---|\n"
                "| 10% | $180.42 |\n"
                "| 20% | $356.66 |\n"
                "| 30% | $552.47 |\n"
                "| 40% | $795.84 |\n"
                "| 50% | $1,132.90 |\n"
                "| 60% | $1,435.02 |\n"
                "| 70% | $1,808.45 |\n"
                "| 80% | $2,102.15 |\n"
                "| 90% | $2,362.30 |\n"
                "| 100% | $3,938.58 |\n\n"
                "**Bilateral factor:** Not applicable (no paired-extremity disabilities).\n\n"
                "**Single biggest rating lever:** documented esophageal dilatation under DC 7206.\n\n"
                "**Update this task as evidence resolves** — once EGD is done, edit which scenario you're tracking toward."
            ),
            "priority": TaskPriority.MEDIUM,
            "status": TaskStatus.IN_PROGRESS,
            "tags": ["phase:reference", "tracker", "pinned", "guide:rating-tracker"],
            "links": [],
        },
        {
            "title": "After-decision plan — supplemental claim / HLR / Board appeal",
            "description": (
                "**Do not file a brand-new claim if denied/underrated.** File the appropriate decision-review form within 1 year of the decision letter:\n\n"
                "  - **Form 20-0995** — Supplemental Claim (new evidence)\n"
                "  - **Form 20-0996** — Higher-Level Review (no new evidence; senior rater takes a fresh look)\n"
                "  - **Form 10182** — Notice of Disagreement → Board of Veterans' Appeals\n\n"
                "**This is the moment to hire a VA-accredited attorney.** Under 38 U.S.C. § 5904, attorneys can charge a fee only AFTER an initial decision. Past-due-benefits fee: ≤20% presumed reasonable, >33⅓% presumed unreasonable.\n\n"
                "**Top firms:**\n"
                "  - **Chisholm Chisholm & Kilpatrick (CCK)** — Providence, RI — premier veterans law firm; recovered $1B+ for veterans since 1999\n"
                "  - **Hill & Ponton** — DeLand, FL — Florida-based, nationwide\n"
                "  - **Berry Law** — Lincoln, NE — veteran-owned; PTSD/anxiety focus\n"
                "  - **Woods & Woods** — Evansville, IN — family-owned, tech-forward\n"
                "  - **Bergmann & Moore** — Bethesda, MD — boutique veterans-only\n\n"
                "**Stay away from claim sharks:**\n"
                "  - Trajector Medical, Veterans Guardian, 'VA coaches' / 'VA Claims Insider Elite'\n"
                "  - Verify EVERY rep at https://www.va.gov/ogc/apps/accreditation/\n"
                "  - Red flags: 'percentage of back pay for initial claim' (illegal), 'guaranteed rating increase,' NDA clauses\n"
                "  - GUARD VA Benefits Act (H.R. 1732, 2025) seeks criminal penalties\n\n"
                "**Benchmark triggers to engage paid counsel earlier:**\n"
                "  - Pre-claim EGD shows stricture/dilatation/aspiration → push for 50% under DC 7206\n"
                "  - Anxiety includes suicidal ideation / near-continuous panic / inability to work → file TDIU concurrently\n"
                "  - C&P examiner produces hostile/factually-wrong report → submit rebuttal evidence\n\n"
                "**CAVC appeal:** hiring an attorney becomes essential — court rules and EAJA fee structure make pro se impractical."
            ),
            "priority": TaskPriority.MEDIUM,
            "status": TaskStatus.BACKLOG,
            "tags": ["phase:reference", "contingency", "guide:after-decision"],
            "links": [
                {"label": "VA accreditation search", "url": "https://www.va.gov/ogc/apps/accreditation/"},
                {"label": "CCK Law", "url": "https://cck-law.com"},
                {"label": "Hill & Ponton", "url": "https://www.hillandponton.com"},
                {"label": "Berry Law", "url": "https://ptsdlawyers.com"},
            ],
        },
        # ---- Added conditions: hearing loss + migraines --------------------------------
        {
            "title": "Log every headache — rating driver for DC 8100 (migraines)",
            "description": (
                "**Start today. Migraines are rated almost entirely on the frequency of *prostrating* attacks, and that record can only be built forward in time.**\n\n"
                "Under 38 C.F.R. § 4.124a, DC 8100:\n"
                "  - **0%** — less frequent attacks\n"
                "  - **10%** — characteristic prostrating attacks averaging one in 2 months over the last several months\n"
                "  - **30%** — characteristic prostrating attacks occurring on an average **once a month** over the last several months\n"
                "  - **50%** — very frequent, completely prostrating and prolonged attacks productive of **severe economic inadaptability**\n\n"
                "**'Prostrating' is the whole ballgame.** It means the attack forces you to stop what you are doing and lie down in a dark, quiet room. A headache you power through does not count. Record it in those terms when it is true.\n\n"
                "**One line per headache:**\n"
                "  - Date and start time\n"
                "  - Duration\n"
                "  - Did you have to stop activity and lie down? (this is the prostrating question — answer it explicitly every time)\n"
                "  - Symptoms: light sensitivity, sound sensitivity, nausea, vomiting, aura, visual disturbance\n"
                "  - Medication taken and whether it worked\n"
                "  - Work impact: late, left early, missed the whole day, or none\n\n"
                "**Also get them treated.** Self-reported headaches with no treatment record are weak evidence. A PCP or neurology note saying 'reports 3-4 prostrating migraines per month' is worth far more than a private log alone — and the log is what produces that sentence at the appointment.\n\n"
                "Bring the log to the neurology C&P exam."
            ),
            "priority": TaskPriority.CRITICAL,
            "status": TaskStatus.TODO,
            "tags": ["phase:7d", "action:evidence", "rating-lever", "condition:migraine", "guide:headache-log"],
            "links": [
                {"label": "38 C.F.R. § 4.124a (DC 8100)", "url": "https://www.law.cornell.edu/cfr/text/38/4.124a"},
            ],
        },
        {
            "title": "Narrative — Bilateral hearing loss (Navy AE noise exposure) (LIVING DOC)",
            "description": (
                "*Edit this description over time. Each save creates an audit-trail event.*\n\n"
                "**Current narrative (v0 — draft):**\n\n"
                "\"I served as an Aviation Electrician's Mate (AE) and worked flight-line and hangar-deck aircraft electrical systems, including engine run-ups and turn-ups, aboard [SHIP] and at [SHORE COMMAND]. Hearing protection was issued but was inadequate or impractical during [SPECIFIC SITUATIONS — e.g., troubleshooting with the aircraft running, intercom communication, emergency flight-deck response].\n\n"
                "I began noticing difficulty hearing during service. Today I have trouble [SPECIFIC EXAMPLES — e.g., following conversation in restaurants or any room with background noise; hearing my [spouse/children] from another room; understanding people on the phone]. I run the television at a volume others say is too loud. I frequently ask people to repeat themselves. My [spouse/family] has commented on it.\"\n\n"
                "**Why this rides along with the tinnitus claim at almost no extra cost:**\n"
                "  - Tinnitus is capped at a flat 10% under DC 6260. Hearing loss is a **separate** rating under DC 6100.\n"
                "  - The in-service noise exposure concession already granted for tinnitus (VBA Fast Letter 10-35: every Navy 'Aviation' rating = 'Highly Probable') covers hearing loss too — it is the same exposure.\n"
                "  - The audiologist performs the audiogram at the Audio C&P exam anyway. It only gets adjudicated if hearing loss is **listed as a claimed condition** on the 21-526EZ.\n\n"
                "**Set expectations honestly:** VA hearing loss must first qualify as a disability under 38 C.F.R. § 3.385 — an auditory threshold of 40 dB or greater at 500, 1000, 2000, 3000, or 4000 Hz; or 26 dB or greater at three of those frequencies; or Maryland CNC speech recognition under 94%. Many veterans rate 0%. A 0% rating is still worth having: it establishes service connection, which makes any future worsening a simple increase rather than a fresh claim.\n\n"
                "**TODO — fill in:** specific ship/squadron names and dates; aircraft types; concrete situations where hearing protection was inadequate; onset timeline; specific present-day examples of difficulty hearing; whether anyone has remarked on it."
            ),
            "priority": TaskPriority.HIGH,
            "status": TaskStatus.IN_PROGRESS,
            "tags": ["phase:reference", "narrative", "condition:hearing", "pinned", "guide:narrative-hearing-loss"],
            "links": [
                {"label": "38 C.F.R. § 3.385 (hearing-loss threshold)", "url": "https://www.law.cornell.edu/cfr/text/38/3.385"},
                {"label": "38 C.F.R. § 4.85 (evaluating hearing impairment)", "url": "https://www.law.cornell.edu/cfr/text/38/4.85"},
            ],
        },
        {
            "title": "Narrative — Migraine headaches (LIVING DOC)",
            "description": (
                "*Edit this description over time. Each save creates an audit-trail event.*\n\n"
                "**Current narrative (v0 — draft):**\n\n"
                "\"I began experiencing severe headaches [IN SERVICE / approximately YEAR] while assigned to [SHIP/SQUADRON/STATION]. [DESCRIBE ANY IN-SERVICE TRIGGER OR TREATMENT — e.g., reported to sick call, treated with (medication), associated with (head injury / noise / sleep deprivation / the GI condition or its medications)].\n\n"
                "The headaches are [DESCRIBE — e.g., one-sided, throbbing, behind the eye], and come with [light sensitivity / sound sensitivity / nausea / vomiting / visual aura]. When one starts I have to [stop what I am doing and lie down in a dark room / leave work / cancel plans]. They last approximately [DURATION] and occur roughly [X] times per month.\n\n"
                "I am currently [treated with MEDICATION by PROVIDER / not receiving treatment]. In the last 12 months they have caused me to [miss X workdays / leave early X times / cancel commitments].\"\n\n"
                "**Establish the theory of service connection — pick the one the records support:**\n"
                "  1. **Direct** — headaches began in service and have continued since (§ 3.303). Strongest if the STR shows any sick-call entry for headaches.\n"
                "  2. **Secondary** (§ 3.310) — headaches proximately due to, or aggravated by, an already-claimed condition. Both anxiety and chronic sleep disruption are recognized headache drivers, and some medications list headache as a common adverse effect.\n"
                "  3. **Aggravation** — pre-existing headaches made permanently worse by service.\n\n"
                "**TODO — fill in:** onset timeline and whether any in-service sick-call entry exists (check the STR once scanned); frequency and duration; whether attacks are prostrating and how often; current treatment and prescriber; documented work impact; which service-connection theory the evidence actually supports."
            ),
            "priority": TaskPriority.HIGH,
            "status": TaskStatus.IN_PROGRESS,
            "tags": ["phase:reference", "narrative", "condition:migraine", "pinned", "guide:narrative-migraines"],
            "links": [
                {"label": "38 C.F.R. § 4.124a (DC 8100)", "url": "https://www.law.cornell.edu/cfr/text/38/4.124a"},
                {"label": "38 C.F.R. § 3.310 (secondary service connection)", "url": "https://www.law.cornell.edu/cfr/text/38/3.310"},
            ],
        },
        {
            "title": "Claim migraine headaches on the 21-526EZ (DC 8100)",
            "description": (
                "Missing from the original playbook entirely, and it is one of the higher-value conditions available.\n\n"
                "**Why it matters:** migraines rate 0 / 10 / 30 / 50% under DC 8100. A 30% rating is realistic with a documented average of one prostrating attack per month, and 30% is the same bracket as the GI condition and anxiety — it is not a rounding error in the combined-rating math.\n\n"
                "**Three things have to be true, and each has its own task:**\n"
                "  1. **A current diagnosis** — see a PCP or neurologist and get 'migraine' (or 'headache disorder') written in the chart. Without a diagnosis there is nothing to rate.\n"
                "  2. **A documented frequency of prostrating attacks** — the headache log task feeds this.\n"
                "  3. **A service-connection theory** — direct (onset in service, § 3.303) or secondary to an already-claimed condition (§ 3.310). The narrative task works this out.\n\n"
                "**Action:** list 'migraine headaches' as a claimed condition on the 21-526EZ. If claiming it as secondary, name the primary condition in exactly the same wording used to list that primary elsewhere on the form — a wording mismatch is a common and entirely avoidable own-goal.\n\n"
                "**Request a neurology C&P exam** (Headaches DBQ). Bring the headache log."
            ),
            "priority": TaskPriority.HIGH,
            "status": TaskStatus.TODO,
            "tags": ["phase:30d", "action:filing", "condition:migraine", "guide:migraines"],
            "links": [
                {"label": "Public DBQs", "url": "https://www.benefits.va.gov/compensation/dbq_publicdbqs.asp"},
                {"label": "38 C.F.R. § 4.124a (DC 8100)", "url": "https://www.law.cornell.edu/cfr/text/38/4.124a"},
            ],
        },
    ]
    return items
