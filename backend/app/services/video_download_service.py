"""
Video download service.

Thin wrapper around `yt-dlp` + `ffmpeg` to download TikTok videos (and other
supported sites) and extract Whisper-friendly audio. Used by the character
reference video pipeline.
"""

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
import structlog

logger = structlog.get_logger()


class VideoDownloadError(Exception):
    """Raised when yt-dlp or ffmpeg fails."""


@dataclass
class DownloadResult:
    video_path: Path
    thumbnail_path: Optional[Path]
    info: dict
    file_size_bytes: int


# TikTok URL patterns
TIKTOK_VIDEO_ID_RE = re.compile(r"/video/(\d+)")
TIKTOK_SHORT_HOSTS = ("vm.tiktok.com", "vt.tiktok.com", "m.tiktok.com")


async def normalize_tiktok_url(url: str, timeout: float = 3.0) -> tuple[str, Optional[str]]:
    """Resolve short TikTok URLs to canonical form and extract the video id.

    Returns `(canonical_url, video_id)` where `video_id` may be None if the URL
    format is unrecognized.
    """
    if not url:
        return url, None

    url = url.strip()
    # Strip surrounding punctuation the share sheet can introduce
    url = url.rstrip(",.;)")

    # Resolve shortlinks by following redirects
    if any(h in url for h in TIKTOK_SHORT_HOSTS) or "/t/" in url:
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
                resp = await client.head(url)
                final_url = str(resp.url)
                if final_url:
                    url = final_url
        except Exception as e:
            logger.info("tiktok_url_redirect_failed", url=url, error=str(e))

    # Strip query string for dedup stability (keep URL readable)
    canonical = url.split("?", 1)[0].rstrip("/")

    # Extract video id
    match = TIKTOK_VIDEO_ID_RE.search(canonical)
    video_id = match.group(1) if match else None

    return canonical, video_id


async def _run_subprocess(
    args: list[str],
    timeout: float,
    cwd: Optional[Path] = None,
) -> tuple[int, str, str]:
    """Run a subprocess with a hard timeout. Returns (returncode, stdout, stderr)."""
    logger.debug("subprocess_start", cmd=args[0], args_count=len(args))
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd) if cwd else None,
        )
    except FileNotFoundError as e:
        raise VideoDownloadError(f"binary not found: {args[0]} ({e})") from e

    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        with _suppress_exceptions():
            proc.kill()
        await _suppress_async(proc.wait())
        raise VideoDownloadError(f"{args[0]} timed out after {timeout}s")

    return proc.returncode or 0, stdout_b.decode("utf-8", errors="replace"), stderr_b.decode("utf-8", errors="replace")


class _suppress_exceptions:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return True


async def _suppress_async(coro):
    try:
        await coro
    except Exception:
        pass


async def download_tiktok(
    url: str,
    dest_dir: Path,
    max_filesize_mb: int = 60,
    timeout_seconds: float = 120.0,
) -> DownloadResult:
    """Download a TikTok video + thumbnail + info.json into `dest_dir`.

    Uses `yt-dlp` via subprocess. Raises `VideoDownloadError` on failure.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Output template (yt-dlp will add extension)
    out_template = str(dest_dir / "video.%(ext)s")

    args = [
        "yt-dlp",
        "--no-playlist",
        "--no-warnings",
        "--no-progress",
        "--format", f"mp4[filesize<{max_filesize_mb}M]/best[ext=mp4][filesize<{max_filesize_mb}M]/best[filesize<{max_filesize_mb}M]",
        "--max-filesize", f"{max_filesize_mb}M",
        "--socket-timeout", "20",
        "--retries", "2",
        "--write-thumbnail",
        "--convert-thumbnails", "jpg",
        "--write-info-json",
        "-o", out_template,
        "--",
        url,
    ]

    rc, stdout, stderr = await _run_subprocess(args, timeout=timeout_seconds)
    if rc != 0:
        # yt-dlp prints useful info to both streams
        tail = (stderr or stdout or "").strip().splitlines()[-5:]
        msg = "\n".join(tail) or f"yt-dlp failed rc={rc}"
        raise VideoDownloadError(msg[:500])

    # Locate the video file
    video_candidates = sorted(dest_dir.glob("video.*"))
    video_file = next((p for p in video_candidates if p.suffix.lower() in (".mp4", ".mov", ".webm", ".mkv")), None)
    if not video_file or not video_file.exists():
        raise VideoDownloadError("yt-dlp produced no video file")

    # Locate thumbnail
    thumb_candidates = sorted(dest_dir.glob("video.jpg"))
    thumbnail = thumb_candidates[0] if thumb_candidates else None
    if not thumbnail:
        # Try other extensions yt-dlp might leave if conversion failed
        for ext in ("webp", "png", "jpeg"):
            candidates = list(dest_dir.glob(f"video.{ext}"))
            if candidates:
                thumbnail = candidates[0]
                break

    # Load info.json
    info: dict = {}
    info_json = dest_dir / "video.info.json"
    if info_json.exists():
        try:
            info = json.loads(info_json.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("info_json_parse_failed", path=str(info_json), error=str(e))

    size = video_file.stat().st_size
    logger.info("tiktok_download_ok", url=url, size_bytes=size, video=str(video_file))

    return DownloadResult(
        video_path=video_file,
        thumbnail_path=thumbnail,
        info=info,
        file_size_bytes=size,
    )


async def extract_audio(
    video_path: Path,
    dest: Path,
    sample_rate: int = 16000,
    bitrate: str = "64k",
    timeout_seconds: float = 60.0,
) -> Path:
    """Extract a mono Whisper-friendly m4a audio track via ffmpeg."""
    dest.parent.mkdir(parents=True, exist_ok=True)

    args = [
        "ffmpeg",
        "-y",
        "-i", str(video_path),
        "-vn",
        "-acodec", "aac",
        "-b:a", bitrate,
        "-ac", "1",
        "-ar", str(sample_rate),
        "-loglevel", "error",
        str(dest),
    ]

    rc, stdout, stderr = await _run_subprocess(args, timeout=timeout_seconds)
    if rc != 0:
        msg = (stderr or stdout or "").strip()[:500] or f"ffmpeg rc={rc}"
        raise VideoDownloadError(f"audio extraction failed: {msg}")

    if not dest.exists() or dest.stat().st_size == 0:
        raise VideoDownloadError("ffmpeg produced no audio output")

    return dest
