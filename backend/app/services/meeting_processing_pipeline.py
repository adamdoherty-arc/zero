"""Meeting AI processing pipeline: transcribe -> diarize -> store -> summarize -> embed."""

import json
import time
import uuid

import structlog
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    MeetingModel, MeetingRecordingModel, MeetingTranscriptSegmentModel, MeetingSummaryModel,
    MeetingSpeakerMappingModel,
)
from app.infrastructure.config import get_settings

logger = structlog.get_logger(__name__)


def _resolve_audio_path(raw_path: str):
    """
    Recordings created by the Zero Host Audio Agent live on the Windows host.
    Zero-api (inside Docker) mounts `./workspace -> /app/workspace`, so a host
    path like `C:\\code\\zero\\workspace\\recordings\\X.wav` appears inside the
    container at `/app/workspace/recordings/X.wav`. Translate here so the
    pipeline can open the file regardless of which process wrote it.
    """
    from pathlib import Path
    p = raw_path.replace("\\", "/")
    # Host path produced by host_agent (default recordings dir).
    for host_prefix in (
        "C:/code/zero/workspace/",
        "c:/code/zero/workspace/",
    ):
        if p.lower().startswith(host_prefix.lower()):
            return Path("/app/workspace/" + p[len(host_prefix):])
    # Legacy host_agent recordings dir (before the shared-workspace move).
    for host_prefix in (
        "C:/code/zero/host_agent/recordings/",
        "c:/code/zero/host_agent/recordings/",
    ):
        if p.lower().startswith(host_prefix.lower()):
            return Path("/app/workspace/recordings/" + p[len(host_prefix):])
    return Path(raw_path)


# WebSocket broadcast clients
_ws_clients: list = []


def register_processing_ws(ws):
    _ws_clients.append(ws)


def unregister_processing_ws(ws):
    if ws in _ws_clients:
        _ws_clients.remove(ws)


async def broadcast_processing_progress(data: dict) -> None:
    import json
    msg = json.dumps(data)
    for ws in _ws_clients[:]:
        try:
            await ws.send_text(msg)
        except Exception:
            _ws_clients.remove(ws)


async def process_meeting_recording(meeting_id: str, db: AsyncSession) -> dict:
    total_start = time.time()
    result = {"meeting_id": meeting_id, "steps": {}}

    # Get recording path
    rec_result = await db.execute(
        select(MeetingRecordingModel).where(MeetingRecordingModel.meeting_id == meeting_id)
    )
    recording = rec_result.scalar_one_or_none()
    if not recording:
        raise ValueError(f"No recording for meeting {meeting_id}")

    from pathlib import Path
    audio_path = _resolve_audio_path(recording.file_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    # --- Step 1: Transcribe ---
    await broadcast_processing_progress({"stage": "transcribing", "progress": 0.0, "message": "Loading transcription model..."})

    from app.services.meeting_transcription_service import get_meeting_transcription_service
    transcription = get_meeting_transcription_service()
    if not transcription.is_loaded:
        transcription.load_model()

    await broadcast_processing_progress({"stage": "transcribing", "progress": 0.2, "message": "Transcribing audio..."})

    t0 = time.time()
    segments = transcription.transcribe(audio_path)
    result["steps"]["transcription"] = {"segments": len(segments), "elapsed_ms": int((time.time() - t0) * 1000)}

    await broadcast_processing_progress({"stage": "transcribing", "progress": 1.0, "message": f"Transcribed {len(segments)} segments"})

    if not segments:
        meeting_result = await db.execute(select(MeetingModel).where(MeetingModel.id == meeting_id))
        meeting = meeting_result.scalar_one_or_none()
        if meeting:
            meeting.status = "completed"
            await db.commit()
        await broadcast_processing_progress({"stage": "complete", "progress": 1.0, "message": "No speech detected"})
        return result

    # --- Step 2: Diarize ---
    diar_segments_raw: list = []
    try:
        await broadcast_processing_progress({"stage": "diarizing", "progress": 0.0, "message": "Running speaker diarization..."})
        from app.services.meeting_diarization_service import get_meeting_diarization_service
        diarization = get_meeting_diarization_service()
        if not diarization.is_loaded:
            diarization.load_model()
        t0 = time.time()
        diar_segments_raw = diarization.diarize(audio_path)
        segments = diarization.align_with_transcript(diar_segments_raw, segments)
        result["steps"]["diarization"] = {"speakers": len(set(s.get("speaker", "") for s in segments)), "elapsed_ms": int((time.time() - t0) * 1000)}
        await broadcast_processing_progress({"stage": "diarizing", "progress": 1.0, "message": "Diarization complete"})
    except Exception as e:
        logger.warning("diarization_skipped", error=str(e))
        result["steps"]["diarization"] = {"skipped": True, "reason": str(e)}

    # --- Step 2b: Voiceprint match ---
    # For each diarized cluster, compute a centroid embedding and look it up in
    # the voiceprints table. When a known identity matches above the threshold,
    # rewrite that cluster's speaker label everywhere downstream.
    label_to_identity: dict[str, str] = {}
    if diar_segments_raw:
        try:
            from app.services.voiceprint_service import get_voiceprint_service
            vp_svc = get_voiceprint_service()
            # Group raw diarization segments by SPEAKER_XX label.
            clusters: dict[str, list[dict]] = {}
            for d in diar_segments_raw:
                clusters.setdefault(d["speaker"], []).append(d)

            t0 = time.time()
            matched = 0
            for label, cluster_segs in clusters.items():
                centroid = vp_svc.compute_cluster_centroid(audio_path, cluster_segs)
                if centroid is None:
                    continue
                match = await vp_svc.match(centroid)
                if match:
                    name, sim = match
                    label_to_identity[label] = name
                    matched += 1
                    logger.info(
                        "voiceprint_matched",
                        meeting_id=meeting_id,
                        label=label,
                        identity=name,
                        similarity=round(sim, 3),
                    )

            if label_to_identity:
                # Rewrite speaker labels on transcript segments.
                for seg in segments:
                    label = seg.get("speaker")
                    if label and label in label_to_identity:
                        seg["speaker"] = label_to_identity[label]

                # Persist mappings so the speaker-mapping UI shows them upfront.
                await db.execute(
                    delete(MeetingSpeakerMappingModel).where(
                        MeetingSpeakerMappingModel.meeting_id == meeting_id
                    )
                )
                for label, name in label_to_identity.items():
                    db.add(MeetingSpeakerMappingModel(
                        meeting_id=meeting_id,
                        speaker_label=label,
                        display_name=name,
                    ))
                await db.commit()

            result["steps"]["voiceprint_match"] = {
                "clusters": len(clusters),
                "matched": matched,
                "elapsed_ms": int((time.time() - t0) * 1000),
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("voiceprint_match_skipped", error=str(e))
            result["steps"]["voiceprint_match"] = {"skipped": True, "reason": str(e)}

    # --- Step 3: Store segments ---
    await broadcast_processing_progress({"stage": "storing", "progress": 0.0, "message": "Saving transcript..."})

    await db.execute(delete(MeetingTranscriptSegmentModel).where(MeetingTranscriptSegmentModel.meeting_id == meeting_id))
    stored_segments = []
    for seg in segments:
        ts = MeetingTranscriptSegmentModel(
            meeting_id=meeting_id, speaker=seg.get("speaker"),
            start_time=seg["start"], end_time=seg["end"],
            text=seg["text"], confidence=seg.get("confidence"),
        )
        db.add(ts)
        stored_segments.append(ts)
    await db.commit()
    # Refresh to get IDs
    for ts in stored_segments:
        await db.refresh(ts)

    # --- Step 4: Summarize ---
    await broadcast_processing_progress({"stage": "summarizing", "progress": 0.0, "message": "Generating summary..."})
    try:
        from app.services.meeting_summary_service import get_meeting_summary_service
        summary_svc = get_meeting_summary_service()

        transcript_lines = [f"[{seg.get('speaker', 'Speaker')}]: {seg['text']}" for seg in segments]
        transcript_text = "\n".join(transcript_lines)

        meeting_result = await db.execute(select(MeetingModel).where(MeetingModel.id == meeting_id))
        meeting = meeting_result.scalar_one_or_none()
        title = meeting.title if meeting else ""

        t0 = time.time()
        summary_data = await summary_svc.summarize(transcript_text, meeting_title=title)
        elapsed = int((time.time() - t0) * 1000)

        await db.execute(delete(MeetingSummaryModel).where(MeetingSummaryModel.meeting_id == meeting_id))
        db.add(MeetingSummaryModel(
            id=uuid.uuid4().hex, meeting_id=meeting_id,
            summary_text=summary_data["summary_text"],
            key_topics=summary_data.get("key_topics", []),
            action_items=summary_data.get("action_items", []),
            decisions=summary_data.get("decisions", []),
            model_used=get_settings().ollama_model,
            generation_time_ms=elapsed,
        ))
        await db.commit()
        result["steps"]["summarization"] = {"elapsed_ms": elapsed}
        await broadcast_processing_progress({"stage": "summarizing", "progress": 1.0, "message": "Summary generated"})
    except Exception as e:
        logger.warning("summarization_failed", error=str(e))
        result["steps"]["summarization"] = {"skipped": True, "reason": str(e)}

    # --- Step 5: Embed ---
    await broadcast_processing_progress({"stage": "embedding", "progress": 0.0, "message": "Indexing for search..."})
    try:
        from app.services.meeting_vector_service import get_meeting_vector_service
        vector_svc = get_meeting_vector_service()

        seg_dicts = [{"id": ts.id, "text": ts.text, "start_time": ts.start_time} for ts in stored_segments]
        count = await vector_svc.embed_segments(meeting_id, seg_dicts, db)
        result["steps"]["embedding"] = {"chunks_indexed": count}
        await broadcast_processing_progress({"stage": "embedding", "progress": 1.0, "message": f"Indexed {count} chunks"})
    except Exception as e:
        logger.warning("embedding_failed", error=str(e))
        result["steps"]["embedding"] = {"skipped": True, "reason": str(e)}

    # --- Update meeting status ---
    meeting_result = await db.execute(select(MeetingModel).where(MeetingModel.id == meeting_id))
    meeting = meeting_result.scalar_one_or_none()
    if meeting:
        meeting.status = "completed"
        await db.commit()

    # --- Step 5b: Auto-create tasks from action items (opt-in) ---
    try:
        from app.routers.meeting_preferences import get_meeting_prefs
        _auto_tasks = bool(get_meeting_prefs().get("auto_create_tasks_from_meetings"))
    except Exception:
        _auto_tasks = get_settings().auto_create_tasks_from_meetings
    if _auto_tasks:
        try:
            from app.routers.meetings import (
                CreateTasksRequest,
                create_tasks_from_action_items,
            )
            t0 = time.time()
            resp = await create_tasks_from_action_items(
                meeting_id,
                CreateTasksRequest(owner_filter="me", auto_assign=True),
            )
            result["steps"]["task_creation"] = {
                "created": len(resp.created),
                "skipped": len(resp.skipped),
                "elapsed_ms": int((time.time() - t0) * 1000),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("auto_task_creation_failed", error=str(exc))
            result["steps"]["task_creation"] = {"skipped": True, "reason": str(exc)}

    # --- Step 6: Save to vault (best-effort) ---
    # Append a human-readable artifact under 00_Meta/_agent/meetings/ so the
    # vault can link to it. Non-fatal: the DB row is the source of truth.
    try:
        summary_result = await db.execute(
            select(MeetingSummaryModel).where(MeetingSummaryModel.meeting_id == meeting_id)
        )
        summary_row = summary_result.scalar_one_or_none()
        if meeting and summary_row:
            from app.services.vault_writer_service import get_vault_writer
            writer = get_vault_writer()
            if writer.available():
                transcript_md_lines = [
                    f"**[{int(seg['start'] // 60):02d}:{int(seg['start'] % 60):02d}] "
                    f"{seg.get('speaker') or 'Speaker'}:** {seg['text']}"
                    for seg in segments
                ]
                writer.write_meeting_summary(
                    meeting_id=meeting_id,
                    title=meeting.title or "Untitled meeting",
                    start_time=meeting.start_time,
                    duration_seconds=meeting.duration_seconds,
                    summary_text=summary_row.summary_text or "",
                    key_topics=list(summary_row.key_topics or []),
                    action_items=list(summary_row.action_items or []),
                    decisions=list(summary_row.decisions or []),
                    transcript="\n".join(transcript_md_lines),
                )
                result["steps"]["vault_save"] = {"ok": True}
    except Exception as e:
        logger.warning("meeting_vault_save_failed", meeting_id=meeting_id, error=str(e))
        result["steps"]["vault_save"] = {"ok": False, "reason": str(e)}

    total_elapsed = int((time.time() - total_start) * 1000)
    result["total_elapsed_ms"] = total_elapsed
    await broadcast_processing_progress({"stage": "complete", "progress": 1.0, "message": f"Processing complete ({total_elapsed / 1000:.1f}s)"})
    logger.info("meeting_processing_complete", meeting_id=meeting_id, elapsed_ms=total_elapsed)
    return result
