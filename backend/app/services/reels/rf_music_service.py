"""Royalty-free / generated music selection for reels.

Reads the ``reel_music_tracks`` table, returns a bakeable track matching the
reel's mood, and self-seeds the procedural beds when the library is empty so
the pipeline is never blocked on music.

Copyright guard: ``select_track`` ONLY returns ``is_bakeable`` rows. The legacy
copyrighted ``music_tracks`` (Hans Zimmer etc.) live in a different table and
are never eligible here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select, update

from app.db.models import ReelMusicTrackModel
from app.infrastructure.database import get_session
from app.models.reel import MusicLicense, MusicSource, ReelMusicTrack

logger = structlog.get_logger(__name__)


# Fallback chain when the exact mood has no track.
_MOOD_FALLBACKS = {
    "epic": ["uplifting", "hopeful", "intense"],
    "intense": ["epic", "dark"],
    "dark": ["intense", "reflective"],
    "hopeful": ["uplifting", "calm"],
    "uplifting": ["hopeful", "epic"],
    "calm": ["reflective", "hopeful"],
    "reflective": ["calm", "dark"],
}


def _to_model(row: ReelMusicTrackModel) -> ReelMusicTrack:
    return ReelMusicTrack(
        id=row.id,
        source=MusicSource(row.source) if row.source in MusicSource._value2member_map_ else MusicSource.RF_LIBRARY,
        provider=row.provider,
        title=row.title,
        artist=row.artist,
        mood=row.mood,
        energy=row.energy,
        bpm=row.bpm,
        beat_grid=list(row.beat_grid_json or []),
        duration_s=row.duration_s,
        license=MusicLicense(row.license) if row.license in MusicLicense._value2member_map_ else MusicLicense.CC0,
        attribution=row.attribution,
        storage_url=row.storage_url,
        local_path=row.local_path,
        loop_safe=bool(row.loop_safe),
    )


async def ensure_seeded() -> int:
    """Make sure at least the procedural beds exist. Returns bakeable count."""
    async with get_session() as session:
        rows = (await session.execute(
            select(ReelMusicTrackModel).where(ReelMusicTrackModel.is_bakeable.is_(True))
        )).scalars().all()
        if rows:
            # Verify the files still exist; if all are missing, re-seed.
            import os
            if any((r.local_path and os.path.exists(r.local_path)) or r.storage_url for r in rows):
                return len(rows)
    from app.services.reels.music_ingest import ingest_procedural
    return await ingest_procedural(force=True)


async def select_track(
    *, mood: Optional[str] = None, energy: Optional[str] = None,
    target_duration_s: Optional[float] = None, track_id: Optional[str] = None,
) -> Optional[ReelMusicTrack]:
    """Pick a bakeable track for the reel. Prefers exact mood + low use_count
    (exploration), then mood fallbacks, then any bakeable track.
    """
    await ensure_seeded()

    async with get_session() as session:
        if track_id:
            row = (await session.execute(
                select(ReelMusicTrackModel).where(
                    ReelMusicTrackModel.id == track_id,
                    ReelMusicTrackModel.is_bakeable.is_(True),
                )
            )).scalar_one_or_none()
            if row:
                await _bump_use(session, row.id)
                return _to_model(row)

        moods_to_try = [mood] if mood else []
        moods_to_try += _MOOD_FALLBACKS.get(mood or "", [])
        chosen: Optional[ReelMusicTrackModel] = None
        for m in moods_to_try:
            q = select(ReelMusicTrackModel).where(
                ReelMusicTrackModel.is_bakeable.is_(True),
                ReelMusicTrackModel.mood == m,
            ).order_by(ReelMusicTrackModel.use_count.asc())
            chosen = (await session.execute(q)).scalars().first()
            if chosen:
                break
        if chosen is None:
            chosen = (await session.execute(
                select(ReelMusicTrackModel).where(
                    ReelMusicTrackModel.is_bakeable.is_(True)
                ).order_by(ReelMusicTrackModel.use_count.asc())
            )).scalars().first()
        if chosen is None:
            logger.warning("reel_music_no_bakeable_track", mood=mood)
            return None
        await _bump_use(session, chosen.id)
        return _to_model(chosen)


async def _bump_use(session, track_id: str) -> None:
    await session.execute(
        update(ReelMusicTrackModel)
        .where(ReelMusicTrackModel.id == track_id)
        .values(use_count=ReelMusicTrackModel.use_count + 1)
    )


async def resolve_local_path(track: ReelMusicTrack) -> Optional[str]:
    """Return a local filesystem path the assembler can feed ffmpeg.

    Procedural/RF tracks are already local. Remote (R2/MinIO) tracks get
    downloaded to a temp file (Phase 2 storage).
    """
    import os
    if track.local_path and os.path.exists(track.local_path):
        return track.local_path
    if track.storage_url:
        try:
            import tempfile
            import httpx
            ext = os.path.splitext(track.storage_url)[1] or ".m4a"
            fd, tmp = tempfile.mkstemp(suffix=ext, prefix="reel_music_")
            os.close(fd)
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as c:
                resp = await c.get(track.storage_url)
                resp.raise_for_status()
                with open(tmp, "wb") as f:
                    f.write(resp.content)
            return tmp
        except Exception as exc:  # noqa: BLE001
            logger.warning("reel_music_download_failed", track=track.id, error=str(exc))
    return None


async def list_tracks(*, bakeable_only: bool = True) -> list[ReelMusicTrack]:
    async with get_session() as session:
        q = select(ReelMusicTrackModel)
        if bakeable_only:
            q = q.where(ReelMusicTrackModel.is_bakeable.is_(True))
        rows = (await session.execute(q.order_by(ReelMusicTrackModel.mood))).scalars().all()
        return [_to_model(r) for r in rows]
