"""Meeting speaker mapping endpoints."""

from pathlib import Path

from fastapi import APIRouter
from sqlalchemy import select, delete
import structlog

from app.db.models import (
    MeetingSpeakerMappingModel,
    MeetingTranscriptSegmentModel,
    MeetingRecordingModel,
)
from app.infrastructure.database import get_session
from app.models.meeting import SpeakerMappingResponse, SpeakerMappingUpdate

router = APIRouter()
logger = structlog.get_logger(__name__)


def _resolve_audio_path(raw_path: str) -> Path:
    """Mirror of meeting_processing_pipeline._resolve_audio_path."""
    p = raw_path.replace("\\", "/")
    for host_prefix in ("C:/code/zero/workspace/", "c:/code/zero/workspace/"):
        if p.lower().startswith(host_prefix.lower()):
            return Path("/app/workspace/" + p[len(host_prefix):])
    for host_prefix in (
        "C:/code/zero/host_agent/recordings/",
        "c:/code/zero/host_agent/recordings/",
    ):
        if p.lower().startswith(host_prefix.lower()):
            return Path("/app/workspace/recordings/" + p[len(host_prefix):])
    return Path(raw_path)


@router.get("/{meeting_id}/speakers")
async def list_speakers(meeting_id: str):
    async with get_session() as db:
        result = await db.execute(
            select(MeetingSpeakerMappingModel).where(MeetingSpeakerMappingModel.meeting_id == meeting_id)
        )
        mappings = result.scalars().all()
        return [SpeakerMappingResponse.model_validate(m) for m in mappings]


@router.put("/{meeting_id}/speakers")
async def update_speakers(meeting_id: str, mappings: list[SpeakerMappingUpdate]):
    async with get_session() as db:
        await db.execute(
            delete(MeetingSpeakerMappingModel).where(MeetingSpeakerMappingModel.meeting_id == meeting_id)
        )
        for m in mappings:
            db.add(MeetingSpeakerMappingModel(
                meeting_id=meeting_id,
                speaker_label=m.speaker_label,
                display_name=m.display_name,
            ))
        await db.commit()

        # Phase 2: persist the speaker as a global voiceprint so future meetings
        # auto-recognise this voice. Best-effort — we don't fail the API call
        # if pyannote / the audio file is unavailable.
        try:
            await _upsert_voiceprints_for_mappings(meeting_id, mappings, db)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "voiceprint_upsert_failed",
                meeting_id=meeting_id,
                error=str(exc),
            )

        result = await db.execute(
            select(MeetingSpeakerMappingModel).where(MeetingSpeakerMappingModel.meeting_id == meeting_id)
        )
        return [SpeakerMappingResponse.model_validate(m) for m in result.scalars().all()]


async def _upsert_voiceprints_for_mappings(
    meeting_id: str,
    mappings: list[SpeakerMappingUpdate],
    db,
) -> None:
    """For each speaker_label → display_name with a real name, compute the
    cluster centroid from the meeting's audio + transcript and store as a
    voiceprint identified by display_name."""
    targets = [m for m in mappings if (m.display_name or "").strip()]
    if not targets:
        return

    rec_row = (
        await db.execute(
            select(MeetingRecordingModel).where(MeetingRecordingModel.meeting_id == meeting_id)
        )
    ).scalar_one_or_none()
    if rec_row is None:
        return
    audio_path = _resolve_audio_path(rec_row.file_path)
    if not audio_path.exists():
        logger.info("voiceprint_upsert_no_audio", meeting_id=meeting_id, path=str(audio_path))
        return

    # Pull all transcript segments once and group by current speaker label.
    segs_rows = (
        await db.execute(
            select(MeetingTranscriptSegmentModel).where(
                MeetingTranscriptSegmentModel.meeting_id == meeting_id
            )
        )
    ).scalars().all()
    by_label: dict[str, list[dict]] = {}
    for s in segs_rows:
        if not s.speaker:
            continue
        by_label.setdefault(s.speaker, []).append(
            {"start": float(s.start_time), "end": float(s.end_time)}
        )

    if not by_label:
        return

    from app.services.voiceprint_service import get_voiceprint_service

    vp_svc = get_voiceprint_service()
    enrolled = 0
    for m in targets:
        cluster = by_label.get(m.speaker_label)
        if not cluster:
            continue
        centroid = vp_svc.compute_cluster_centroid(audio_path, cluster)
        if centroid is None:
            continue
        await vp_svc.enroll(
            display_name=m.display_name.strip(),
            embedding=centroid,
            samples_seconds=sum(c["end"] - c["start"] for c in cluster),
            is_primary=False,
            source_meeting_id=meeting_id,
        )
        enrolled += 1
    if enrolled:
        logger.info(
            "voiceprint_upsert_complete",
            meeting_id=meeting_id,
            enrolled=enrolled,
        )
