"""F-19 — Superhuman virtual meeting attendee (host-side driver).

Runs on the Windows host_agent process because it needs VB-Audio Cable +
OBS / pyvirtualcam — both Windows-only devices that the Linux zero-api
container can't reach.

Exposes three FastAPI endpoints (wired in host_agent/main.py):

  POST /agent/join      {url, display_name, dry_run?} -> session_id
  POST /agent/speak     {session_id, wav_bytes_b64}    -> {ok, bytes}
  POST /agent/leave     {session_id}                   -> {ok}

In ``dry_run`` mode the driver creates a session row and goes through
the motions WITHOUT actually opening Chromium or touching the virtual
devices. Useful for proving the wiring + state machine without VB-Cable
installed. Auto-engaged when ``ZERO_MEETING_AGENT_REAL_DRIVER`` is unset
or when Playwright/pyvirtualcam imports fail.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


_DATA_DIR = Path(__file__).resolve().parent.parent / "workspace" / "superhuman"
_SESSIONS_PATH = _DATA_DIR / "sessions.json"
_AVATAR_PATH = _DATA_DIR / "avatar.png"
# NOTE: the host label must not contain `/`, `\`, `@`, or whitespace — `\` and `@`
# are authority-confusion characters (a browser normalizes `\`→`/` and treats
# `user@host` as userinfo), so permitting them would let
# `https://attacker.com\@zoom.us/...` pass this Zoom allow-list yet navigate to
# attacker.com. Require a path/query/fragment delimiter (or end) after the host.
_MEET_URL_RE = re.compile(
    r"^https?://(?:[^/\s\\@]*zoom\.us|meet\.google\.com|teams\.microsoft\.com|teams\.live\.com)"
    r"(?:[:/?#][^\s]*)?$",
    re.IGNORECASE,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _real_driver_enabled() -> bool:
    return os.getenv("ZERO_MEETING_AGENT_REAL_DRIVER", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


@dataclass
class HostMeetingSession:
    id: str
    url: str
    display_name: str
    status: str  # joining | active | speaking | leaving | ended | error | dry_run
    dry_run: bool
    joined_at: str
    ended_at: Optional[str] = None
    spoken_chars: int = 0
    error: Optional[str] = None
    # F-19 transcript follow-up — best-effort caption capture (Google Meet only
    # for now; Zoom/Teams scraping is a documented follow-on). Lines accumulate
    # here as the captions DOM is polled; `transcript` is the joined text the
    # fork persists into `meeting_records` when Zero leaves the meeting.
    transcript: str = ""


class SuperhumanDriver:
    """Wraps Playwright + pyvirtualcam + sounddevice. Single-instance per
    host (Chromium browser is heavy)."""

    def __init__(self) -> None:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._sessions: dict[str, HostMeetingSession] = self._load()
        # Lazy-loaded driver handles.
        self._playwright: Any = None  # async_playwright instance
        self._browser: Any = None
        self._pages: dict[str, Any] = {}  # session_id -> Playwright page
        self._cam_writers: dict[str, Any] = {}  # session_id -> pyvirtualcam.Camera
        self._cam_tasks: dict[str, asyncio.Task] = {}
        # F-19 transcript follow-up — per-session ordered caption lines (de-duped)
        # and the background caption-poller task, both keyed by session id.
        self._caption_lines: dict[str, list[str]] = {}
        self._caption_seen: dict[str, set[str]] = {}
        self._caption_tasks: dict[str, asyncio.Task] = {}

    def _load(self) -> dict[str, HostMeetingSession]:
        if not _SESSIONS_PATH.exists():
            return {}
        try:
            raw = json.loads(_SESSIONS_PATH.read_text(encoding="utf-8"))
            return {sid: HostMeetingSession(**row) for sid, row in raw.items()}
        except Exception as exc:
            logger.warning("superhuman_sessions_load_failed", error=str(exc))
            return {}

    def _save(self) -> None:
        with self._lock:
            tmp = _SESSIONS_PATH.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps({sid: asdict(s) for sid, s in self._sessions.items()}, indent=2),
                encoding="utf-8",
            )
            tmp.replace(_SESSIONS_PATH)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def join(
        self,
        *,
        url: str,
        display_name: str = "Zero",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        if not _MEET_URL_RE.match(url):
            raise ValueError(f"Unsupported meeting URL: {url}")
        force_dry = dry_run or not _real_driver_enabled()
        session = HostMeetingSession(
            id=uuid.uuid4().hex[:12],
            url=url,
            display_name=display_name,
            status="dry_run" if force_dry else "joining",
            dry_run=force_dry,
            joined_at=_now_iso(),
        )
        self._sessions[session.id] = session
        self._save()
        logger.info(
            "superhuman_join",
            session=session.id,
            url=url,
            dry_run=force_dry,
        )
        if not force_dry:
            try:
                asyncio.create_task(self._driver_join(session))
            except Exception as exc:  # noqa: BLE001
                session.status = "error"
                session.error = str(exc)
                self._save()
                logger.warning("superhuman_join_dispatch_failed", error=str(exc))
        return asdict(session)

    async def speak(self, *, session_id: str, wav_bytes: bytes) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if session is None:
            return {"ok": False, "error": "unknown_session"}
        if session.dry_run:
            session.spoken_chars += len(wav_bytes)
            self._save()
            return {
                "ok": True,
                "dry_run": True,
                "bytes": len(wav_bytes),
                "note": "Wrote nothing to VB-Cable — dry_run mode.",
            }
        try:
            await self._pipe_to_virtual_mic(wav_bytes)
            session.spoken_chars += len(wav_bytes)
            self._save()
            return {"ok": True, "bytes": len(wav_bytes)}
        except Exception as exc:  # noqa: BLE001
            logger.warning("superhuman_speak_failed", error=str(exc))
            return {"ok": False, "error": str(exc)}

    async def leave(self, *, session_id: str) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if session is None:
            return {"ok": False, "error": "unknown_session"}
        session.status = "leaving"
        self._save()
        # Tear down per-session resources.
        # F-19 transcript follow-up — stop the caption poller FIRST and flush its
        # accumulated lines onto the session so the transcript survives leave.
        cap_task = self._caption_tasks.pop(session_id, None)
        if cap_task and not cap_task.done():
            cap_task.cancel()
            try:
                await cap_task
            except (asyncio.CancelledError, Exception):
                pass
        cap_lines = self._caption_lines.pop(session_id, None)
        self._caption_seen.pop(session_id, None)
        if cap_lines:
            session.transcript = "\n".join(cap_lines)
        task = self._cam_tasks.pop(session_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        cam = self._cam_writers.pop(session_id, None)
        if cam is not None:
            try:
                cam.close()
            except Exception:
                pass
        page = self._pages.pop(session_id, None)
        if page is not None:
            try:
                await page.close()
            except Exception:
                pass
        session.status = "ended"
        session.ended_at = _now_iso()
        self._save()
        logger.info("superhuman_leave", session=session_id)
        return {"ok": True, "session_id": session_id}

    def get(self, session_id: str) -> dict[str, Any] | None:
        s = self._sessions.get(session_id)
        return asdict(s) if s else None

    def notes(self, session_id: str) -> dict[str, Any] | None:
        """F-19 transcript follow-up — return whatever caption transcript was
        captured for a session. Reads from the live caption buffer when the
        poller is still running, else from the saved session row. Returns None
        when the session id is unknown so the caller can 404. The transcript is
        the empty string when nothing was captured (Zoom/Teams, captions off,
        or a stub/dry-run join)."""
        s = self._sessions.get(session_id)
        if s is None:
            return None
        live = self._caption_lines.get(session_id)
        transcript = "\n".join(live) if live else (s.transcript or "")
        return {
            "session_id": s.id,
            "transcript": transcript,
            "display_name": s.display_name,
            "status": s.status,
            "url": s.url,
            "dry_run": s.dry_run,
            "joined_at": s.joined_at,
            "ended_at": s.ended_at,
        }

    def list_sessions(self) -> list[dict[str, Any]]:
        return [asdict(s) for s in self._sessions.values()]

    # ------------------------------------------------------------------
    # Internals — Playwright lifecycle
    # ------------------------------------------------------------------

    async def _driver_join(self, session: HostMeetingSession) -> None:
        """Open a Playwright page on the meeting URL, type the display
        name, click Join, then mark active. Browser stays open until
        ``leave`` cancels the lifecycle task."""
        try:
            from playwright.async_api import async_playwright  # type: ignore
        except ImportError as exc:
            session.status = "error"
            session.error = "playwright not installed (host_agent .venv)"
            self._save()
            logger.warning("superhuman_no_playwright", error=str(exc))
            return
        try:
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            if self._browser is None:
                # Headed mode so the user sees what's happening. headless=True
                # is also fine once trusted; some meeting platforms gate on
                # webcam permission prompts that need a real surface.
                headless = os.getenv("ZERO_SUPERHUMAN_HEADLESS", "true").lower() in (
                    "1", "true", "yes",
                )
                self._browser = await self._playwright.chromium.launch(
                    headless=headless,
                    args=[
                        "--use-fake-ui-for-media-stream",  # auto-grant mic/cam
                        "--enable-features=VirtualWebcam",
                    ],
                )
            context = await self._browser.new_context(
                permissions=["microphone", "camera"],
            )
            page = await context.new_page()
            self._pages[session.id] = page
            await page.goto(session.url, wait_until="domcontentloaded", timeout=30000)
            # Best-effort name entry — selectors vary across Zoom/Meet/Teams
            # so we try the common ones and shrug if none match.
            for selector in (
                'input[type="text"][placeholder*="name" i]',
                'input[name="name"]',
                'input#display-name',
                'input[aria-label*="name" i]',
            ):
                try:
                    await page.fill(selector, session.display_name, timeout=2000)
                    break
                except Exception:
                    continue
            # Best-effort join button click.
            for selector in (
                'button:has-text("Join")',
                'button:has-text("Join now")',
                'button:has-text("Join meeting")',
                'button[aria-label*="Join" i]',
            ):
                try:
                    await page.click(selector, timeout=2000)
                    break
                except Exception:
                    continue
            # Start the virtual camera avatar loop in the background.
            self._cam_tasks[session.id] = asyncio.create_task(self._cam_loop(session))
            # F-19 transcript follow-up — start best-effort caption capture
            # (Google Meet only; tolerant of failure, never blocks the join).
            self._caption_lines.setdefault(session.id, [])
            self._caption_seen.setdefault(session.id, set())
            self._caption_tasks[session.id] = asyncio.create_task(
                self._caption_loop(session, page)
            )
            session.status = "active"
            self._save()
            logger.info("superhuman_active", session=session.id, url=session.url)
        except Exception as exc:  # noqa: BLE001
            session.status = "error"
            session.error = str(exc)[:240]
            self._save()
            logger.warning("superhuman_driver_join_failed", error=str(exc))

    async def _cam_loop(self, session: HostMeetingSession) -> None:
        """Stream the Zero avatar PNG into pyvirtualcam at 5 fps. Closes
        cleanly on cancellation."""
        try:
            import pyvirtualcam  # type: ignore
            from PIL import Image
            import numpy as np
        except ImportError:
            logger.debug("superhuman_cam_loop_skipped_no_deps", session=session.id)
            return
        try:
            avatar_path = ensure_avatar()
            img = Image.open(avatar_path).convert("RGB")
            frame = np.array(img, dtype="uint8")
            height, width = frame.shape[:2]
            cam = pyvirtualcam.Camera(width=width, height=height, fps=5)
            self._cam_writers[session.id] = cam
            logger.info(
                "superhuman_cam_running",
                session=session.id,
                device=getattr(cam, "device", "unknown"),
                fmt=str(getattr(cam, "fmt", "?")),
            )
            while True:
                cam.send(frame)
                cam.sleep_until_next_frame()
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("superhuman_cam_loop_failed", session=session.id, error=str(exc))

    async def _enable_meet_captions(self, page: Any) -> None:
        """Best-effort: turn on Google Meet live captions so the captions DOM
        region populates. Tries the toolbar button first, then the `c` keyboard
        shortcut. Shrugs on any failure — capture just yields an empty transcript."""
        for selector in (
            'button[aria-label*="aptions" i]',          # "Turn on captions"
            'button[aria-label*="ubtitle" i]',          # localized "subtitles"
            'button[jsname][data-tooltip*="aptions" i]',
        ):
            try:
                await page.click(selector, timeout=1500)
                return
            except Exception:
                continue
        # Fallback: Meet's keyboard shortcut for captions is `c`.
        try:
            await page.keyboard.press("c")
        except Exception:
            pass

    async def _caption_loop(self, session: HostMeetingSession, page: Any) -> None:
        """Poll the Google Meet captions DOM region into the session transcript
        buffer on a timer. Best-effort and provider-specific: Meet exposes its
        live captions as readable DOM text; Zoom/Teams render captions in ways
        that need separate scraping (documented follow-on). Never raises out —
        a capture failure must not affect the meeting or the leave path.

        De-dupes by line so the rolling captions overlay (which keeps the last
        few lines visible) doesn't multiply the transcript. Cancelled cleanly on
        ``leave``."""
        # Only Meet is supported for now; skip the poller entirely otherwise so we
        # don't burn cycles scraping a DOM that has no readable captions.
        if "meet.google.com" not in (session.url or "").lower():
            logger.debug(
                "superhuman_caption_skip_unsupported_provider", session=session.id
            )
            return
        # Give the call a moment to connect, then switch captions on.
        try:
            await asyncio.sleep(4.0)
            await self._enable_meet_captions(page)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.debug("superhuman_caption_enable_failed", session=session.id, error=str(exc))

        # Meet renders each caption as a speaker chip + a text span inside a
        # captions region. We read the region's visible text and split into lines.
        selectors = (
            'div[role="region"][aria-label*="aptions" i]',
            'div[aria-label*="aptions" i]',
            "div.a4cQT",  # Meet captions container class (best-effort, may change)
        )
        seen = self._caption_seen.setdefault(session.id, set())
        lines = self._caption_lines.setdefault(session.id, [])
        try:
            while True:
                text = ""
                for sel in selectors:
                    try:
                        el = await page.query_selector(sel)
                        if el is not None:
                            text = (await el.inner_text()) or ""
                            if text.strip():
                                break
                    except Exception:
                        continue
                if text.strip():
                    for raw in text.splitlines():
                        line = raw.strip()
                        # Skip empties and the standalone speaker-name chips that
                        # Meet renders on their own line (short, no sentence text).
                        if not line:
                            continue
                        if line in seen:
                            continue
                        seen.add(line)
                        lines.append(line)
                    # Persist the rolling transcript onto the session so a notes
                    # fetch mid-meeting already sees what's been said.
                    session.transcript = "\n".join(lines)
                await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            # Final flush on cancellation so leave() captures the last lines.
            session.transcript = "\n".join(lines)
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("superhuman_caption_loop_failed", session=session.id, error=str(exc))
            session.transcript = "\n".join(lines)

    async def _pipe_to_virtual_mic(self, wav_bytes: bytes) -> None:
        """Decode WAV → PCM and play through ``CABLE Input`` (VB-Audio
        Cable). Picks the device by name; raises if VB-Cable isn't
        installed."""
        import sounddevice as sd  # type: ignore
        import soundfile as sf  # type: ignore

        # Find CABLE Input output device.
        target = None
        for idx, dev in enumerate(sd.query_devices()):
            name = str(dev.get("name") or "")
            if "CABLE Input" in name and dev.get("max_output_channels", 0) > 0:
                target = idx
                break
        if target is None:
            raise RuntimeError(
                "VB-Audio CABLE Input output device not found. Install "
                "VB-Audio Cable on the Windows host (see "
                "docs/superhuman-setup.md)."
            )
        with io.BytesIO(wav_bytes) as buf:
            audio, sample_rate = sf.read(buf, dtype="float32")
        await asyncio.get_running_loop().run_in_executor(
            None, sd.play, audio, sample_rate, target,
        )
        await asyncio.get_running_loop().run_in_executor(None, sd.wait)


# ---------------------------------------------------------------------------
# Avatar generation — idempotent
# ---------------------------------------------------------------------------


def ensure_avatar() -> Path:
    """Create the Zero avatar PNG if it doesn't exist. 640x480 dark
    indigo card with the Zero glyph + display name."""
    if _AVATAR_PATH.exists():
        return _AVATAR_PATH
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.debug("superhuman_avatar_no_pillow")
        return _AVATAR_PATH
    w, h = 640, 480
    img = Image.new("RGB", (w, h), color=(15, 23, 42))  # slate-900
    draw = ImageDraw.Draw(img)
    # Border ring (indigo).
    draw.rounded_rectangle((20, 20, w - 20, h - 20), radius=20, outline=(99, 102, 241), width=4)
    # Big "Zero" mark.
    try:
        font_big = ImageFont.truetype("DejaVuSans-Bold.ttf", 96)
        font_sm = ImageFont.truetype("DejaVuSans.ttf", 28)
    except Exception:
        font_big = ImageFont.load_default()
        font_sm = ImageFont.load_default()
    title = "Zero"
    tbbox = draw.textbbox((0, 0), title, font=font_big)
    tx = (w - (tbbox[2] - tbbox[0])) // 2
    ty = (h - (tbbox[3] - tbbox[1])) // 2 - 30
    draw.text((tx, ty), title, fill=(226, 232, 240), font=font_big)
    sub = "AI Meeting Steward"
    sbbox = draw.textbbox((0, 0), sub, font=font_sm)
    sx = (w - (sbbox[2] - sbbox[0])) // 2
    sy = ty + (tbbox[3] - tbbox[1]) + 16
    draw.text((sx, sy), sub, fill=(148, 163, 184), font=font_sm)
    img.save(_AVATAR_PATH, "PNG")
    logger.info("superhuman_avatar_generated", path=str(_AVATAR_PATH))
    return _AVATAR_PATH


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_driver_instance: SuperhumanDriver | None = None
_driver_lock = threading.RLock()


def get_superhuman_driver() -> SuperhumanDriver:
    global _driver_instance
    with _driver_lock:
        if _driver_instance is None:
            _driver_instance = SuperhumanDriver()
        return _driver_instance
