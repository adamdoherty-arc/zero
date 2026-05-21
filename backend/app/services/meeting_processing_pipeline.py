"""Meeting AI processing pipeline: transcribe -> diarize -> store -> summarize -> embed."""

import json
import os
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
    transcription_seconds = round(time.time() - t0, 2)
    result["steps"]["transcription"] = {"segments": len(segments), "elapsed_ms": int(transcription_seconds * 1000)}

    await broadcast_processing_progress({"stage": "transcribing", "progress": 1.0, "message": f"Transcribed {len(segments)} segments"})

    # F-82: record per-meeting cost telemetry (transcription leg).
    try:
        from app.services.meeting_cost_service import get_meeting_cost_service

        audio_seconds_total = 0.0
        if segments:
            try:
                audio_seconds_total = float(segments[-1].get("end", 0.0))
            except Exception:
                audio_seconds_total = 0.0
        get_meeting_cost_service().record(
            meeting_id=meeting_id,
            transcription_seconds=transcription_seconds,
            transcription_model=getattr(transcription, "model_name", None)
            or os.getenv("REACHY_LOCAL_WHISPER_MODEL", "distil-large-v3"),
            audio_seconds=audio_seconds_total,
        )
    except Exception as exc:
        logger.debug("meeting_cost_transcription_record_failed", error=str(exc))

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

    # --- Step 2c: Face match (Feature-52) ---
    # If host_agent captured camera frames during the meeting, cluster the
    # detected faces and rewrite SPEAKER_XX labels for diarized turns whose
    # midpoint falls within a frame timestamp range of a matched face cluster.
    try:
        from app.services.meeting_face_service import (
            extract_faces_from_meeting,
            get_faceprint_service,
        )
        from app.infrastructure.config import get_workspace_path

        frames_dir = get_workspace_path("meetings") / meeting_id / "frames"
        if frames_dir.exists():
            t0 = time.time()
            clusters = extract_faces_from_meeting(meeting_id, frames_dir)
            face_svc = get_faceprint_service()
            # Feature-57 — best-effort auto-enroll attendees we don't have
            # a face for yet, using their Google profile photo. Runs
            # before match so the new enrollments are eligible to match
            # this meeting's clusters in a single pass.
            try:
                attendees_for_enroll = list(getattr(meeting, "participants", None) or [])
                if attendees_for_enroll:
                    auto_enrolled = await face_svc.auto_enroll_from_attendees(
                        attendees_for_enroll,
                        meeting_id=meeting_id,
                    )
                    if auto_enrolled:
                        result["steps"]["face_auto_enroll"] = {
                            "enrolled": auto_enrolled,
                            "count": len(auto_enrolled),
                        }
            except Exception as exc:  # noqa: BLE001
                logger.debug("face_auto_enroll_skipped", meeting_id=meeting_id, error=str(exc))
            face_labels: dict[int, str] = {}
            for cluster in clusters:
                if cluster.centroid is None:
                    continue
                m = await face_svc.match(cluster.centroid.astype("float32"))
                if m:
                    face_labels[cluster.cluster_id] = m[0]
                    logger.info(
                        "face_match",
                        meeting_id=meeting_id,
                        cluster=cluster.cluster_id,
                        identity=m[0],
                        similarity=round(m[1], 3),
                        frames=len(cluster.frames),
                    )

            # Build (start_ms, end_ms, identity) windows from matched clusters.
            matched_windows = []
            for cluster in clusters:
                name = face_labels.get(cluster.cluster_id)
                if not name:
                    continue
                start_ms, end_ms = cluster.ts_range
                matched_windows.append((start_ms, end_ms, name))

            # Align: a transcript segment whose midpoint falls within any
            # window inherits that identity. This complements voiceprint
            # alignment -- if voiceprint already named the speaker, we don't
            # overwrite it (voice is more discriminative than imagehash).
            recording_start_ms = None
            if recording and recording.created_at:
                recording_start_ms = int(recording.created_at.timestamp() * 1000)
            face_assigned = 0
            for seg in segments:
                if seg.get("speaker") and not seg["speaker"].startswith("SPEAKER_"):
                    # Already named (probably by voiceprint match).
                    continue
                mid_ms = int(((seg["start"] + seg["end"]) / 2.0) * 1000)
                if recording_start_ms is not None:
                    mid_ms += recording_start_ms
                for start_ms, end_ms, name in matched_windows:
                    if start_ms <= mid_ms <= end_ms:
                        seg["speaker"] = name
                        face_assigned += 1
                        break

            result["steps"]["face_match"] = {
                "clusters": len(clusters),
                "matched_identities": len(face_labels),
                "segments_renamed": face_assigned,
                "elapsed_ms": int((time.time() - t0) * 1000),
            }
        else:
            result["steps"]["face_match"] = {"skipped": True, "reason": "no_frames"}
    except Exception as e:  # noqa: BLE001
        logger.warning("face_match_skipped", error=str(e))
        result["steps"]["face_match"] = {"skipped": True, "reason": str(e)}

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

    # --- Step 3b: Topic segmentation (F-76) ---
    # Runs before summarization + vault write so the vault file ships
    # with topic anchors. Pure lexical / silence-based; no LLM, no
    # embeddings, ~constant time relative to transcript length.
    try:
        from app.services.meeting_topic_segmenter import (
            segment_transcript,
            get_meeting_topic_store,
        )

        seg_dicts_for_topics = [
            {
                "text": getattr(ts, "text", "") or "",
                "start": float(getattr(ts, "start_time", 0.0) or 0.0),
                "end": float(getattr(ts, "end_time", 0.0) or 0.0),
            }
            for ts in stored_segments
        ]
        topics = segment_transcript(seg_dicts_for_topics)
        get_meeting_topic_store().write(meeting_id, topics)
        result["steps"]["topics"] = {
            "topic_count": len(topics),
            "labels": [t.label for t in topics[:8]],
        }
    except Exception as exc:
        logger.warning("topic_segmentation_failed", error=str(exc))
        result["steps"]["topics"] = {"skipped": True, "reason": str(exc)}

    # --- Step 4: Summarize ---
    await broadcast_processing_progress({"stage": "summarizing", "progress": 0.0, "message": "Generating summary..."})
    try:
        from app.services.meeting_summary_service import get_meeting_summary_service
        from app.services.meeting_privacy_service import (
            get_meeting_privacy_service,
        )
        summary_svc = get_meeting_summary_service()

        meeting_result = await db.execute(select(MeetingModel).where(MeetingModel.id == meeting_id))
        meeting = meeting_result.scalar_one_or_none()
        title = meeting.title if meeting else ""

        # Audit-47 — private meetings must not propagate to an LLM. The
        # transcript stays on disk for the user but no summary is generated,
        # no LLM call is made, and downstream gates (vault writer, follow-up
        # service, RAG embed) continue to honour the flag.
        is_private = get_meeting_privacy_service().is_private(meeting_id)
        if is_private:
            summary_data: dict = {
                "summary_text": "",
                "key_topics": [],
                "action_items": [],
                "decisions": [],
                "token_count": 0,
            }
            elapsed = 0
            result["steps"]["summarization"] = {"skipped": True, "reason": "private"}
            logger.info("meeting_summary_skipped_private", meeting_id=meeting_id)
            # Wipe any prior summary too — the user marked it private, so
            # remove a stale public summary if one already existed.
            await db.execute(delete(MeetingSummaryModel).where(MeetingSummaryModel.meeting_id == meeting_id))
            await db.commit()
            await broadcast_processing_progress({"stage": "summarizing", "progress": 1.0, "message": "Private meeting — summary skipped"})
        else:
            transcript_lines = [f"[{seg.get('speaker', 'Speaker')}]: {seg['text']}" for seg in segments]
            transcript_text = "\n".join(transcript_lines)
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

        # F-82: record summary leg of cost telemetry.
        try:
            from app.services.meeting_cost_service import get_meeting_cost_service

            get_meeting_cost_service().record(
                meeting_id=meeting_id,
                summary_tokens=int(summary_data.get("token_count") or 0)
                or len((summary_data.get("summary_text") or "").split()) * 2,  # rough estimate
                summary_model=get_settings().ollama_model,
                summary_ms=elapsed,
            )
        except Exception as exc:
            logger.debug("meeting_cost_summary_record_failed", error=str(exc))

        # F-44 — write the summary to /vault/Meetings/<YYYY>/<MM>/. Private
        # meetings get a stub-only file (no transcript content). Best-
        # effort: never fail the pipeline if the vault mount is missing.
        try:
            from app.services.meeting_vault_writer import (
                get_meeting_vault_writer,
            )
            from app.services.meeting_privacy_service import (
                get_meeting_privacy_service,
            )

            speakers = sorted({
                str(s.get("speaker") or "")
                for s in segments
                if s.get("speaker")
            })
            # F-83: include topics in vault render if F-76 has produced them.
            topics_for_vault: list[dict[str, Any]] = []
            try:
                from app.services.meeting_topic_segmenter import (
                    get_meeting_topic_store,
                )
                cached = get_meeting_topic_store().read(meeting_id)
                if cached and cached.get("topics"):
                    topics_for_vault = list(cached["topics"])
            except Exception:
                topics_for_vault = []
            vault_res = get_meeting_vault_writer().write(
                meeting_id=meeting_id,
                title=title or "Untitled meeting",
                start_time=meeting.start_time if meeting else None,
                end_time=meeting.end_time if meeting else None,
                attendees=list(getattr(meeting, "participants", None) or []),
                summary_text=summary_data.get("summary_text", "") or "",
                key_topics=summary_data.get("key_topics", []) or [],
                action_items=summary_data.get("action_items", []) or [],
                decisions=summary_data.get("decisions", []) or [],
                transcript_segment_count=len(segments),
                recording_path=getattr(recording, "file_path", None) if recording else None,
                speakers=speakers,
                private=get_meeting_privacy_service().is_private(meeting_id),
                topics=topics_for_vault,
            )
            result["steps"]["vault_write"] = vault_res
            logger.info(
                "meeting_vault_write",
                meeting_id=meeting_id,
                ok=vault_res.get("ok"),
                path=vault_res.get("path"),
            )
        except Exception as exc:
            logger.warning("meeting_vault_write_failed", meeting_id=meeting_id, error=str(exc))
            result["steps"]["vault_write"] = {"skipped": True, "reason": str(exc)}
    except Exception as e:
        logger.warning("summarization_failed", error=str(e))
        result["steps"]["summarization"] = {"skipped": True, "reason": str(e)}

    # --- Step 5: Embed ---
    # Audit-47 — private meetings stay out of the RAG / vector store so
    # the dashboard's cross-meeting chat can't surface them.
    from app.services.meeting_privacy_service import get_meeting_privacy_service
    if get_meeting_privacy_service().is_private(meeting_id):
        result["steps"]["embedding"] = {"skipped": True, "reason": "private"}
        await broadcast_processing_progress({"stage": "embedding", "progress": 1.0, "message": "Private meeting — embedding skipped"})
        logger.info("meeting_embedding_skipped_private", meeting_id=meeting_id)
    else:
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
