"""Reel orchestrator — runs the full quote→MP4 pipeline in-process.

This is the single source of stage logic. The Temporal activities
(``app.workflows.activities.reels``) are thin wrappers over the same stage
functions, so the pipeline is identical whether it runs durably (Temporal) or
directly (this module / the autonomous loop / tests). Phase-1 verification runs
this directly so it doesn't depend on the Temporal worker being up.

Phase 1 stages: source quote → plan scenes → render frames (gradient bg) →
[optional voiceover] → select music → assemble MP4 → upload → persist →
[optional dry-run publish]. AI visuals/music + judge/reflexion + IG/YT land in
Phases 2-4.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog

from app.models.reel import (
    MotivationReel,
    ReelGenerationStatus,
    ReelSubNiche,
    ReelWorkflowInput,
    ReelWorkflowResult,
    SUBNICHE_DEFAULT_MOOD,
)
from app.services.reels import (
    quote_source_service,
    reel_design_service,
    reel_frame_service,
    reel_publish_service,
    reel_state,
    rf_music_service,
    video_assembly_service,
)

logger = structlog.get_logger(__name__)


async def _persist(reel: MotivationReel, status: ReelGenerationStatus, *,
                   initiated_by: Optional[str] = None, error: Optional[str] = None) -> None:
    reel.status = status.value if hasattr(status, "value") else status
    await reel_state.upsert_reel_state(reel, status=reel.status,
                                       initiated_by=initiated_by, error=error)


async def generate_reel(payload: ReelWorkflowInput, *, generation_id: Optional[str] = None,
                        workflow_id: Optional[str] = None) -> ReelWorkflowResult:
    """Run the full reel pipeline. Returns a ReelWorkflowResult."""
    gen_id = generation_id or uuid.uuid4().hex
    sub_niche = payload.sub_niche or ReelSubNiche.STOICISM.value
    mood = payload.mood or SUBNICHE_DEFAULT_MOOD.get(sub_niche, "reflective")

    reel = MotivationReel(
        id=gen_id, workflow_id=workflow_id, sub_niche=sub_niche, theme=payload.theme,
        mood=mood, voiceover=payload.voiceover, visual_style=payload.visual_style or "gradient",
        created_at=datetime.now(timezone.utc),
    )
    await _persist(reel, ReelGenerationStatus.SOURCING, initiated_by=payload.initiated_by)

    workdir = tempfile.mkdtemp(prefix=f"reel_{gen_id[:8]}_")
    music_tmp: Optional[str] = None
    try:
        # 1. Quote --------------------------------------------------------
        exclude = await _recent_quote_hashes(sub_niche)
        quote = await quote_source_service.select_quote(
            sub_niche=sub_niche, theme=payload.theme, exclude_hashes=exclude,
            explicit_text=payload.quote_text, explicit_author=payload.quote_author,
        )
        reel.quote = quote
        reel.theme = reel.theme or quote.theme
        await _persist(reel, ReelGenerationStatus.PLANNING)

        # 2. Scene plan ---------------------------------------------------
        scenes = await reel_design_service.plan_scenes(
            quote, sub_niche=sub_niche, scene_count=payload.scene_count,
            target_duration_s=payload.target_duration_s, mood=mood,
        )
        reel.scenes = scenes
        cta_text = next((s.text for s in scenes if s.role.value == "cta"), None)
        caption, hashtags = reel_design_service.compose_caption(
            quote, sub_niche=sub_niche, cta_text=cta_text or "Follow for more.")
        reel.caption, reel.hashtags, reel.cta_text = caption, hashtags, cta_text
        await _persist(reel, ReelGenerationStatus.RENDERING)

        # 3. Render frames (text baked in) --------------------------------
        frames = await reel_frame_service.render_scene_frames(scenes, mood=mood, quote=quote)
        if not frames or not any(frames):
            raise RuntimeError("frame render produced no frames")

        # 4. Optional voiceover ------------------------------------------
        voiceover_path: Optional[str] = None
        if payload.voiceover:
            await _persist(reel, ReelGenerationStatus.VOICING)
            voiceover_path = await _synth_voiceover(quote, scenes, workdir)

        # 5. Music --------------------------------------------------------
        track = await rf_music_service.select_track(
            mood=mood, target_duration_s=payload.target_duration_s,
            track_id=payload.music_track_id,
        )
        reel.music_track = track
        if track:
            music_tmp = await rf_music_service.resolve_local_path(track)

        # 6. Assemble -----------------------------------------------------
        await _persist(reel, ReelGenerationStatus.ASSEMBLING)
        out_mp4 = os.path.join(workdir, "reel.mp4")
        assembled = await video_assembly_service.assemble_reel(
            frames=frames,
            scene_durations=[s.duration_s for s in scenes],
            motions=[s.motion if isinstance(s.motion, str) else s.motion.value for s in scenes],
            music_path=music_tmp,
            voiceover_path=voiceover_path,
            out_path=out_mp4,
        )
        reel.duration_s = round(assembled.duration_s, 2)

        # 7. Upload -------------------------------------------------------
        with open(assembled.out_path, "rb") as f:
            mp4_bytes = f.read()
        reel.video_sha256 = hashlib.sha256(mp4_bytes).hexdigest()
        reel.video_url = await _store_mp4(gen_id, mp4_bytes)
        logger.info("reel_assembled", generation_id=gen_id, duration=reel.duration_s,
                    size=len(mp4_bytes), used_fallback=assembled.used_fallback,
                    video_url=reel.video_url)

        # 8. Review / publish --------------------------------------------
        await _persist(reel, ReelGenerationStatus.AWAITING_REVIEW)
        if payload.auto_publish:
            await _persist(reel, ReelGenerationStatus.PUBLISHING)
            pubs = await reel_publish_service.publish_reel(reel, platforms=payload.platforms)
            reel.platform_publishes = pubs
            reel.published_at = datetime.now(timezone.utc)
            await _persist(reel, ReelGenerationStatus.PUBLISHED)

        return ReelWorkflowResult(
            generation_id=gen_id, reel_id=gen_id, status=reel.status,
            video_url=reel.video_url, duration_s=reel.duration_s,
            composite_score=reel.composite_score, platform_publishes=reel.platform_publishes,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("reel_generation_failed", generation_id=gen_id, error=str(exc))
        await _persist(reel, ReelGenerationStatus.FAILED, error=str(exc)[:500])
        return ReelWorkflowResult(
            generation_id=gen_id, reel_id=gen_id, status=ReelGenerationStatus.FAILED.value,
            error=str(exc)[:500],
        )
    finally:
        _cleanup(workdir, music_tmp, keep_dirs=True)


async def _recent_quote_hashes(sub_niche: str, limit: int = 60) -> set[str]:
    """Dedup guard — don't reuse a quote shipped recently in this niche."""
    try:
        rows = await reel_state.list_reels(limit=limit, sub_niche=sub_niche)
        hashes = set()
        for r in rows:
            q = r.get("quote") or {}
            txt = q.get("text")
            if txt:
                hashes.add(quote_source_service.quote_sha256(txt))
        return hashes
    except Exception:  # noqa: BLE001
        return set()


async def _synth_voiceover(quote, scenes, workdir: str) -> Optional[str]:
    """Phase 1: one narration of hook + quote + cta, ducked under music."""
    try:
        from app.services.tts_service import get_tts_service
        lines = []
        for s in scenes:
            if s.voiceover_text:
                lines.append(s.voiceover_text)
        narration = ". ".join(lines) if lines else quote.text
        path = os.path.join(workdir, "vo.wav")
        tts = get_tts_service()
        await tts.synthesize_to_file(narration, path)
        return path if os.path.exists(path) else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("reel_voiceover_failed", error=str(exc))
        return None


def reel_local_path(gen_id: str) -> str:
    local_dir = os.getenv("ZERO_REEL_OUTPUT_DIR", "/app/app/data/reels")
    return os.path.join(local_dir, f"{gen_id}.mp4")


async def _store_mp4(gen_id: str, body: bytes) -> str:
    """Persist the master MP4 locally (served via the API for review) and make a
    best-effort R2/MinIO upload for future public-URL publishing (Phase 3).

    Returns the API serving path, which always works for the review UI.
    """
    local_dir = os.getenv("ZERO_REEL_OUTPUT_DIR", "/app/app/data/reels")
    try:
        os.makedirs(local_dir, exist_ok=True)
        with open(reel_local_path(gen_id), "wb") as f:
            f.write(body)
    except Exception as exc:  # noqa: BLE001
        logger.warning("reel_mp4_local_store_failed", generation_id=gen_id, error=str(exc))
    # Best-effort remote upload (needed for TikTok PULL_FROM_URL in Phase 3).
    try:
        from app.services.carousel_v2 import r2_uploader
        await r2_uploader.upload_image(
            body=body, key=f"reels/{gen_id}/reel.mp4", content_type="video/mp4"
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("reel_mp4_remote_upload_skipped", generation_id=gen_id, error=str(exc))
    return f"/api/reels/{gen_id}/video"


def _cleanup(workdir: str, music_tmp: Optional[str], *, keep_dirs: bool) -> None:
    import shutil
    try:
        if music_tmp and music_tmp.startswith(tempfile.gettempdir()) and os.path.exists(music_tmp):
            os.unlink(music_tmp)
    except OSError:
        pass
    if not keep_dirs:
        try:
            shutil.rmtree(workdir, ignore_errors=True)
        except OSError:
            pass
