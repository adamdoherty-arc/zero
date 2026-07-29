"""Music ingest for the reel RF library.

Phase 1 ships a **self-contained, copyright-clean** seed: per-mood ambient beds
synthesised procedurally with ffmpeg (layered detuned oscillators + tremolo +
lowpass + reverb). License is ``generated_owned`` so they're bakeable into a
monetized MP4 with zero attribution burden and zero network dependency.

Phase 2 layers real curated CC0 tracks (``ingest_from_urls``) and AI music
behind the same ``reel_music_tracks`` table + ``rf_music_service`` interface;
BPM/beat-grid extraction upgrades from the synthesised nominal to ``librosa``.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Optional

import structlog
from sqlalchemy import select

from app.db.models import ReelMusicTrackModel
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)


def music_dir() -> Path:
    d = Path(os.getenv("ZERO_REEL_MUSIC_DIR", "/app/app/data/reel_music"))
    d.mkdir(parents=True, exist_ok=True)
    return d


# Per-mood synthesis recipe: a low triad (Hz) + nominal tempo + energy.
_MOOD_BEDS = {
    "calm":       {"freqs": (110.00, 130.81, 164.81), "bpm": 70,  "energy": "low",    "lp": 1100},
    "reflective": {"freqs": (98.00, 123.47, 146.83),  "bpm": 72,  "energy": "low",    "lp": 1000},
    "hopeful":    {"freqs": (130.81, 164.81, 196.00), "bpm": 90,  "energy": "medium", "lp": 1400},
    "uplifting":  {"freqs": (146.83, 185.00, 220.00), "bpm": 96,  "energy": "medium", "lp": 1600},
    "epic":       {"freqs": (130.81, 196.00, 261.63), "bpm": 100, "energy": "high",   "lp": 1800},
    "intense":    {"freqs": (73.42, 110.00, 146.83),  "bpm": 130, "energy": "high",   "lp": 1500},
    "dark":       {"freqs": (65.41, 98.00, 130.81),   "bpm": 80,  "energy": "medium", "lp": 900},
}

_BED_DURATION_S = 30.0


def _ffmpeg_bin() -> str:
    import shutil
    return os.getenv("ZERO_FFMPEG_BIN") or shutil.which("ffmpeg") or "ffmpeg"


async def _synth_bed(mood: str, recipe: dict, out_path: Path) -> bool:
    """Render one ambient bed with ffmpeg. Returns True on success."""
    f1, f2, f3 = recipe["freqs"]
    d = _BED_DURATION_S
    lp = recipe["lp"]
    args = [
        _ffmpeg_bin(), "-y",
        "-f", "lavfi", "-i", f"sine=frequency={f1}:duration={d}",
        "-f", "lavfi", "-i", f"sine=frequency={f2}:duration={d}",
        "-f", "lavfi", "-i", f"sine=frequency={f3}:duration={d}",
        "-f", "lavfi", "-i", f"sine=frequency={f1*2:.2f}:duration={d}",
        "-filter_complex",
        (
            "[0]volume=0.50,tremolo=f=0.16:d=0.35[a0];"
            "[1]volume=0.38,tremolo=f=0.11:d=0.30[a1];"
            "[2]volume=0.30[a2];"
            "[3]volume=0.16[a3];"
            "[a0][a1][a2][a3]amix=inputs=4:normalize=0,"
            f"lowpass=f={lp},aecho=0.8:0.7:55|110:0.35|0.2,"
            f"afade=t=in:st=0:d=2.5,afade=t=out:st={d - 2.5}:d=2.5,"
            "loudnorm=I=-18:TP=-1.5:LRA=11"
        ),
        "-ar", "44100", "-c:a", "aac", "-b:a", "160k", str(out_path),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await asyncio.wait_for(proc.communicate(), timeout=120)
        ok = (proc.returncode == 0) and out_path.exists() and out_path.stat().st_size > 2048
        if not ok:
            logger.warning("reel_music_synth_failed", mood=mood,
                           tail=(err or b"").decode("utf-8", "replace")[-300:])
        return ok
    except Exception as exc:  # noqa: BLE001
        logger.warning("reel_music_synth_error", mood=mood, error=str(exc))
        return False


def _beat_grid_from_bpm(bpm: float, duration: float) -> list[float]:
    if bpm <= 0:
        return []
    step = 60.0 / bpm
    n = int(duration / step)
    return [round(i * step, 3) for i in range(n)]


async def ingest_procedural(*, force: bool = False) -> int:
    """Generate per-mood ambient beds + insert/refresh ``reel_music_tracks`` rows.

    Idempotent: existing procedural rows (whose files still exist) are kept
    unless ``force``. Returns the number of tracks now available.
    """
    out_dir = music_dir()
    created = 0
    async with get_session() as session:
        existing = {
            r.mood: r for r in (await session.execute(
                select(ReelMusicTrackModel).where(ReelMusicTrackModel.provider == "procedural")
            )).scalars().all()
        }
        for mood, recipe in _MOOD_BEDS.items():
            row = existing.get(mood)
            path = out_dir / f"bed_{mood}.m4a"
            file_ok = path.exists() and path.stat().st_size > 2048
            if row is not None and file_ok and not force:
                continue
            if not file_ok or force:
                if not await _synth_bed(mood, recipe, path):
                    continue
            bpm = float(recipe["bpm"])
            fields = dict(
                source="rf_library", provider="procedural",
                title=f"{mood.title()} Ambient Bed", artist="Zero Synth",
                mood=mood, energy=recipe["energy"], bpm=bpm,
                beat_grid_json=_beat_grid_from_bpm(bpm, _BED_DURATION_S),
                duration_s=_BED_DURATION_S, license="generated_owned",
                attribution=None, storage_url=None, local_path=str(path),
                loop_safe=True, is_bakeable=True,
            )
            if row is None:
                session.add(ReelMusicTrackModel(id=uuid.uuid4().hex, **fields))
                created += 1
            else:
                for k, v in fields.items():
                    setattr(row, k, v)
        await session.flush()
    total = await _count_bakeable()
    logger.info("reel_music_ingest_procedural_done", created=created, total_bakeable=total)
    return total


async def _count_bakeable() -> int:
    async with get_session() as session:
        rows = (await session.execute(
            select(ReelMusicTrackModel).where(ReelMusicTrackModel.is_bakeable.is_(True))
        )).scalars().all()
        return len(rows)


async def ingest_from_urls(tracks: list[dict]) -> int:
    """Phase 2 hook — download curated CC0 tracks + extract BPM via librosa.

    ``tracks``: list of {url, title, artist, mood, energy, license, attribution}.
    Stub-safe: tolerates per-track failure, returns count ingested.
    """
    import httpx

    out_dir = music_dir()
    ingested = 0
    async with get_session() as session:
        for t in tracks:
            try:
                url = t["url"]
                ext = os.path.splitext(url)[1] or ".mp3"
                tid = uuid.uuid4().hex
                path = out_dir / f"rf_{tid}{ext}"
                async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as c:
                    resp = await c.get(url)
                    resp.raise_for_status()
                    path.write_bytes(resp.content)
                bpm, grid, dur = await _probe_audio(path)
                session.add(ReelMusicTrackModel(
                    id=tid, source="rf_library", provider=t.get("provider", "cc0"),
                    title=t.get("title", "Untitled"), artist=t.get("artist"),
                    mood=t.get("mood"), energy=t.get("energy"), bpm=bpm,
                    beat_grid_json=grid, duration_s=dur,
                    license=t.get("license", "cc0"), attribution=t.get("attribution"),
                    local_path=str(path), source_url=url,
                    loop_safe=t.get("loop_safe", True),
                    is_bakeable=t.get("license", "cc0") in {"cc0", "cc_by", "commercial"},
                ))
                ingested += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("reel_music_url_ingest_failed", url=t.get("url"), error=str(exc))
        await session.flush()
    return ingested


async def _probe_audio(path: Path) -> tuple[Optional[float], list[float], Optional[float]]:
    """Best-effort BPM + beat-grid + duration. librosa if present, else ffprobe."""
    try:
        import librosa  # optional dep

        def _work():
            y, sr = librosa.load(str(path), mono=True)
            tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
            times = librosa.frames_to_time(beats, sr=sr)
            dur = float(librosa.get_duration(y=y, sr=sr))
            return float(tempo), [round(float(t), 3) for t in times], dur

        return await asyncio.to_thread(_work)
    except Exception:  # noqa: BLE001
        from app.services.reels.video_assembly_service import probe_duration
        dur = await probe_duration(str(path))
        return None, [], dur
