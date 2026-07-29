"""Video assembly — the core new capability for motivation reels.

Takes rendered scene frames (each already has its quote text baked in by the
Playwright renderer) and muxes them into a single 1080×1920 H.264 MP4 with:

- per-scene Ken-Burns / pan motion (``zoompan``),
- crossfade transitions (``xfade``) between scenes,
- a baked royalty-free / generated background track (looped + trimmed to length),
- optional voiceover ducked under the music (``sidechaincompress``),
- EBU R128 loudness normalisation to **-14 LUFS** (the platform target).

One master MP4 serves TikTok / IG Reels / YT Shorts.

Design choices (see plan §C):
- We drive **ffmpeg directly** via ``asyncio.create_subprocess_exec`` (natively
  async, no event-loop blocking) rather than moviepy (RAM blowup at 1080×1920×N)
  or the external AIContentTools :8085 service (separate, currently-down).
- ffmpeg is already in the zero-api image (``backend/Dockerfile``).
- Every ffmpeg invocation is guarded; on failure we fall back to a simpler
  concat (no motion), then to a single static frame, so the pipeline never
  hard-fails on a filter-graph quirk.

Beat-synced animated captions (ASS karaoke) are Phase 2 — Phase 1 bakes the
text into the frames, so this stage is motion + audio only.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

import structlog

logger = structlog.get_logger(__name__)


DEFAULT_FPS = 30
DEFAULT_W = 1080
DEFAULT_H = 1920
DEFAULT_CROSSFADE_S = 0.45
DEFAULT_LUFS = -14.0


@dataclass
class ReelAssemblyResult:
    out_path: str
    duration_s: float
    has_audio: bool
    width: int = DEFAULT_W
    height: int = DEFAULT_H
    used_fallback: bool = False
    ffmpeg_log_tail: str = ""


@dataclass
class _SceneInput:
    frame_path: str
    duration_s: float
    motion: str = "ken_burns_in"


def _ffmpeg_bin() -> str:
    return os.getenv("ZERO_FFMPEG_BIN") or shutil.which("ffmpeg") or "ffmpeg"


def _ffprobe_bin() -> str:
    return os.getenv("ZERO_FFPROBE_BIN") or shutil.which("ffprobe") or "ffprobe"


def _motion_exprs(motion: str, frames: int) -> tuple[str, str, str]:
    """Return (zoom_expr, x_expr, y_expr) for a zoompan over ``frames`` frames.

    ``on`` is the cumulative output-frame index zoompan exposes. Expressions are
    written against the (already 2× upscaled) input so panning has headroom.
    """
    frames = max(frames, 1)
    center_x = "iw/2-(iw/zoom/2)"
    center_y = "ih/2-(ih/zoom/2)"
    if motion == "ken_burns_out":
        return (f"max(1.25-0.0012*on,1.0)", center_x, center_y)
    if motion == "pan_left":
        return ("1.15", f"(iw-iw/zoom)*(1-on/{frames})", center_y)
    if motion == "pan_right":
        return ("1.15", f"(iw-iw/zoom)*(on/{frames})", center_y)
    if motion == "static":
        return ("1.001", center_x, center_y)
    # default: ken_burns_in
    return (f"min(1.0+0.0012*on,1.25)", center_x, center_y)


def _build_video_filtergraph(
    scenes: Sequence[_SceneInput],
    *,
    fps: int,
    width: int,
    height: int,
    crossfade_s: float,
) -> tuple[str, str]:
    """Build the video half of the filter_complex. Returns (graph, out_label)."""
    parts: list[str] = []
    labels: list[str] = []
    up_w, up_h = width * 2, height * 2

    for i, sc in enumerate(scenes):
        n_frames = max(int(round(sc.duration_s * fps)), 1)
        zexpr, xexpr, yexpr = _motion_exprs(sc.motion, n_frames)
        # The trailing ``fps`` filter + ``settb`` are load-bearing: ``xfade``
        # rejects inputs without a constant frame rate, and zoompan/trim leave
        # the rate metadata unset (1/0). Forcing CFR here fixes
        # "inputs needs to be a constant frame rate".
        parts.append(
            f"[{i}:v]"
            f"scale={up_w}:{up_h}:force_original_aspect_ratio=increase,"
            f"crop={up_w}:{up_h},"
            f"zoompan=z='{zexpr}':x='{xexpr}':y='{yexpr}':d=1:"
            f"s={width}x{height}:fps={fps},"
            f"trim=duration={sc.duration_s:.3f},setpts=PTS-STARTPTS,"
            f"fps={fps},settb=AVTB,setsar=1,format=yuv420p[v{i}]"
        )
        labels.append(f"[v{i}]")

    if len(scenes) == 1:
        return ";".join(parts), labels[0].strip("[]")

    # Chain xfades. offset_j = sum(dur[0..j-1]) - j*crossfade.
    cur_label = "v0"
    cum = scenes[0].duration_s
    for j in range(1, len(scenes)):
        offset = max(cum - j * crossfade_s, 0.05)
        out_label = f"vx{j}"
        trans = "fade" if j % 2 == 1 else "smoothleft"
        parts.append(
            f"[{cur_label}][v{j}]"
            f"xfade=transition={trans}:duration={crossfade_s:.3f}:offset={offset:.3f}"
            f"[{out_label}]"
        )
        cur_label = out_label
        cum += scenes[j].duration_s
    return ";".join(parts), cur_label


def _total_duration(scenes: Sequence[_SceneInput], crossfade_s: float) -> float:
    total = sum(s.duration_s for s in scenes)
    if len(scenes) > 1:
        total -= (len(scenes) - 1) * crossfade_s
    return max(total, 0.5)


async def _run_ffmpeg(args: list[str], *, timeout: float = 600.0) -> tuple[int, str]:
    """Run ffmpeg, returning (returncode, stderr_tail). Never raises."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return 124, "ffmpeg timed out"
        tail = (stderr or b"").decode("utf-8", "replace")[-2000:]
        return proc.returncode or 0, tail
    except FileNotFoundError:
        return 127, "ffmpeg binary not found"
    except Exception as exc:  # noqa: BLE001
        return 1, f"ffmpeg launch failed: {exc}"


async def probe_duration(path: str) -> Optional[float]:
    """ffprobe the duration of a media file (seconds). None on failure."""
    try:
        proc = await asyncio.create_subprocess_exec(
            _ffprobe_bin(), "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        return float(out.decode().strip())
    except Exception:  # noqa: BLE001
        return None


def _audio_chain(
    *,
    n_video_inputs: int,
    music_idx: Optional[int],
    voiceover_idx: Optional[int],
    total: float,
    target_lufs: float,
    music_gain_db: float,
) -> tuple[list[str], Optional[str]]:
    """Build the audio half of filter_complex. Returns (parts, out_label)."""
    parts: list[str] = []
    fade_out_start = max(total - 1.2, 0.0)

    if music_idx is None and voiceover_idx is None:
        return [], None

    if voiceover_idx is not None and music_idx is not None:
        # Duck music under the voiceover, then mix.
        parts.append(
            f"[{music_idx}:a]volume={music_gain_db}dB,"
            f"atrim=0:{total:.3f},asetpts=PTS-STARTPTS[mraw]"
        )
        parts.append(f"[{voiceover_idx}:a]apad=pad_dur=0.2,asetpts=PTS-STARTPTS[vo]")
        parts.append(
            "[mraw][vo]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=400[mduck]"
        )
        parts.append(
            f"[mduck][vo]amix=inputs=2:duration=first:dropout_transition=2,"
            f"afade=t=out:st={fade_out_start:.3f}:d=1.2,"
            f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11[aout]"
        )
        return parts, "aout"

    src = music_idx if music_idx is not None else voiceover_idx
    gain = music_gain_db if music_idx is not None else 0.0
    parts.append(
        f"[{src}:a]volume={gain}dB,atrim=0:{total:.3f},asetpts=PTS-STARTPTS,"
        f"afade=t=out:st={fade_out_start:.3f}:d=1.2,"
        f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11[aout]"
    )
    return parts, "aout"


async def assemble_reel(
    *,
    frames: Sequence[bytes],
    scene_durations: Sequence[float],
    motions: Optional[Sequence[str]] = None,
    music_path: Optional[str] = None,
    voiceover_path: Optional[str] = None,
    out_path: Optional[str] = None,
    fps: int = DEFAULT_FPS,
    width: int = DEFAULT_W,
    height: int = DEFAULT_H,
    crossfade_s: float = DEFAULT_CROSSFADE_S,
    target_lufs: float = DEFAULT_LUFS,
    music_gain_db: float = -2.0,
) -> ReelAssemblyResult:
    """Assemble scene frames + audio into a 1080×1920 H.264 MP4.

    ``frames`` are JPEG/PNG bytes, one per scene (text already baked in).
    Returns a :class:`ReelAssemblyResult`. Never raises — on ffmpeg failure it
    degrades to a motionless concat, then to a single static frame.
    """
    if not frames:
        raise ValueError("assemble_reel: no frames provided")

    motions = list(motions or [])
    # Clamp crossfade so it never exceeds the shortest scene.
    min_dur = min(scene_durations) if scene_durations else 3.0
    crossfade_s = max(0.1, min(crossfade_s, min_dur * 0.6))

    workdir = Path(tempfile.mkdtemp(prefix="reel_assembly_"))
    if out_path is None:
        out_path = str(workdir / "reel.mp4")

    scenes: list[_SceneInput] = []
    for i, body in enumerate(frames):
        fp = workdir / f"frame_{i:03d}.jpg"
        fp.write_bytes(body)
        dur = float(scene_durations[i]) if i < len(scene_durations) else 3.0
        motion = motions[i] if i < len(motions) else (
            "ken_burns_in" if i % 2 == 0 else "ken_burns_out"
        )
        scenes.append(_SceneInput(str(fp), max(dur, 0.8), motion))

    total = _total_duration(scenes, crossfade_s)
    has_music = bool(music_path and os.path.exists(music_path))
    has_vo = bool(voiceover_path and os.path.exists(voiceover_path))

    try:
        result = await _assemble_full(
            scenes, out_path=out_path, fps=fps, width=width, height=height,
            crossfade_s=crossfade_s, total=total,
            music_path=music_path if has_music else None,
            voiceover_path=voiceover_path if has_vo else None,
            target_lufs=target_lufs, music_gain_db=music_gain_db,
        )
        if result is not None:
            return result

        logger.warning("reel_assembly_full_failed_falling_back")
        result = await _assemble_concat_fallback(
            scenes, out_path=out_path, fps=fps, width=width, height=height,
            total=total, music_path=music_path if has_music else None,
            target_lufs=target_lufs,
        )
        if result is not None:
            result.used_fallback = True
            return result

        # Last resort: a single static frame as a short video so the pipeline
        # always yields a playable MP4.
        result = await _assemble_static_fallback(
            scenes[0], out_path=out_path, fps=fps, width=width, height=height,
            total=total, music_path=music_path if has_music else None,
        )
        if result is None:
            raise RuntimeError("all ffmpeg assembly paths failed")
        result.used_fallback = True
        return result
    finally:
        # Keep the output file; clean intermediate frames only if out_path is
        # outside workdir.
        if not str(Path(out_path).resolve()).startswith(str(workdir.resolve())):
            for f in workdir.glob("frame_*.jpg"):
                try:
                    f.unlink()
                except OSError:
                    pass


async def _assemble_full(
    scenes: list[_SceneInput], *, out_path: str, fps: int, width: int, height: int,
    crossfade_s: float, total: float, music_path: Optional[str],
    voiceover_path: Optional[str], target_lufs: float, music_gain_db: float,
) -> Optional[ReelAssemblyResult]:
    args: list[str] = [_ffmpeg_bin(), "-y"]

    # Image inputs (one looped still per scene).
    for sc in scenes:
        args += ["-loop", "1", "-framerate", str(fps), "-t", f"{sc.duration_s:.3f}",
                 "-i", sc.frame_path]

    music_idx: Optional[int] = None
    vo_idx: Optional[int] = None
    next_idx = len(scenes)
    if music_path:
        args += ["-stream_loop", "-1", "-i", music_path]
        music_idx = next_idx
        next_idx += 1
    if voiceover_path:
        args += ["-i", voiceover_path]
        vo_idx = next_idx
        next_idx += 1

    vgraph, vlabel = _build_video_filtergraph(
        scenes, fps=fps, width=width, height=height, crossfade_s=crossfade_s
    )
    agraph_parts, alabel = _audio_chain(
        n_video_inputs=len(scenes), music_idx=music_idx, voiceover_idx=vo_idx,
        total=total, target_lufs=target_lufs, music_gain_db=music_gain_db,
    )

    filter_complex = vgraph
    if agraph_parts:
        filter_complex += ";" + ";".join(agraph_parts)

    args += ["-filter_complex", filter_complex, "-map", f"[{vlabel}]"]
    if alabel:
        args += ["-map", f"[{alabel}]"]
    args += [
        "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-r", str(fps), "-b:v", "8M", "-maxrate", "10M", "-bufsize", "16M",
    ]
    if alabel:
        args += ["-c:a", "aac", "-b:a", "192k", "-ar", "44100"]
    args += ["-t", f"{total:.3f}", "-movflags", "+faststart", out_path]

    code, tail = await _run_ffmpeg(args)
    if code != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) < 1024:
        logger.warning("reel_assembly_full_ffmpeg_error", code=code, tail=tail[-600:])
        return None

    dur = await probe_duration(out_path) or total
    logger.info("reel_assembly_full_ok", out=out_path, duration=round(dur, 2),
                scenes=len(scenes), has_audio=bool(alabel))
    return ReelAssemblyResult(out_path=out_path, duration_s=dur,
                              has_audio=bool(alabel), width=width, height=height,
                              ffmpeg_log_tail=tail[-400:])


async def _assemble_concat_fallback(
    scenes: list[_SceneInput], *, out_path: str, fps: int, width: int, height: int,
    total: float, music_path: Optional[str], target_lufs: float,
) -> Optional[ReelAssemblyResult]:
    """No motion / no xfade — plain hard-cut concat. Robust last-but-one path."""
    args: list[str] = [_ffmpeg_bin(), "-y"]
    for sc in scenes:
        args += ["-loop", "1", "-framerate", str(fps), "-t", f"{sc.duration_s:.3f}",
                 "-i", sc.frame_path]
    music_idx: Optional[int] = None
    if music_path:
        args += ["-stream_loop", "-1", "-i", music_path]
        music_idx = len(scenes)

    parts = []
    for i in range(len(scenes)):
        parts.append(
            f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,fps={fps},format=yuv420p[v{i}]"
        )
    concat_inputs = "".join(f"[v{i}]" for i in range(len(scenes)))
    parts.append(f"{concat_inputs}concat=n={len(scenes)}:v=1:a=0[vout]")
    alabel = None
    if music_idx is not None:
        parts.append(
            f"[{music_idx}:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,"
            f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11[aout]"
        )
        alabel = "aout"

    args += ["-filter_complex", ";".join(parts), "-map", "[vout]"]
    if alabel:
        args += ["-map", f"[{alabel}]", "-c:a", "aac", "-b:a", "192k"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
             "-t", f"{total:.3f}", "-movflags", "+faststart", out_path]

    code, tail = await _run_ffmpeg(args)
    if code != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) < 1024:
        logger.warning("reel_assembly_concat_error", code=code, tail=tail[-600:])
        return None
    dur = await probe_duration(out_path) or total
    return ReelAssemblyResult(out_path=out_path, duration_s=dur,
                              has_audio=alabel is not None, width=width, height=height)


async def _assemble_static_fallback(
    scene: _SceneInput, *, out_path: str, fps: int, width: int, height: int,
    total: float, music_path: Optional[str],
) -> Optional[ReelAssemblyResult]:
    args = [_ffmpeg_bin(), "-y", "-loop", "1", "-framerate", str(fps),
            "-t", f"{total:.3f}", "-i", scene.frame_path]
    if music_path:
        args += ["-stream_loop", "-1", "-i", music_path]
    args += [
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,"
               f"crop={width}:{height},setsar=1,format=yuv420p",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
    ]
    if music_path:
        args += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
    args += ["-t", f"{total:.3f}", "-movflags", "+faststart", out_path]
    code, tail = await _run_ffmpeg(args)
    if code != 0 or not os.path.exists(out_path):
        logger.error("reel_assembly_static_error", code=code, tail=tail[-400:])
        return None
    dur = await probe_duration(out_path) or total
    return ReelAssemblyResult(out_path=out_path, duration_s=dur,
                              has_audio=bool(music_path), width=width, height=height)
