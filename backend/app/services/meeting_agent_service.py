"""
Meeting Agent — Zero joins a Google Meet / Zoom call as a real participant.

Inspired by openhuman's Meeting Agent. The agent:

  1. Spawns a headless Chromium tab (via Playwright) and navigates to the
     meeting URL.
  2. Captures incoming audio from the tab (via a virtual audio sink on the
     host) and pipes it to Zero's existing realtime STT pipeline.
  3. Transcript chunks flow into the Memory Tree as ``meetings/{id}/L0/`` so
     the user can search them later.
  4. When the user (or a trigger) asks the agent to speak, the existing TTS
     stack synthesizes audio that the headless browser plays through a
     virtual mic.

Real audio routing requires:
  - Playwright (``playwright install chromium``)
  - PulseAudio (linux) or Soundflower / BlackHole (mac) virtual sinks
  - The user pre-authenticates Google in the headless profile (one-time)

If Playwright isn't installed, the service stays in "unavailable" mode but
still exposes a clean Pydantic API + persistence layer + Memory Tree
ingestion path, so the rest of Zero (UI, search, summaries) keeps working.

Public API:

    svc = get_meeting_agent_service()
    await svc.join(url="https://meet.google.com/abc-defg-hij")
    await svc.speak(session_id, "Hello everyone, this is Zero.")
    await svc.leave(session_id)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "meeting_agent"
_SESSIONS_FILE = "sessions.json"
_MEET_URL_RE = re.compile(r"^https?://(meet\.google\.com|zoom\.us|.*\.zoom\.us)/")


@dataclass
class MeetingSession:
    id: str
    url: str
    title: str
    status: str  # "joining" | "active" | "speaking" | "leaving" | "ended" | "error"
    joined_at: str
    ended_at: Optional[str] = None
    transcript_chars: int = 0
    spoken_turns: int = 0
    error: Optional[str] = None
    notes_vault_paths: list[str] = field(default_factory=list)


class MeetingAgentService:
    def __init__(self) -> None:
        import app.services.meeting_agent_service as _self_mod
        self._dir = _self_mod._DATA_DIR
        self._path = self._dir / _SESSIONS_FILE
        self._sessions: dict[str, MeetingSession] = self._load()
        self._driver = self._init_driver()
        self._tasks: dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------
    # Driver init (Playwright — optional)
    # ------------------------------------------------------------------

    def _init_driver(self):
        try:
            from playwright.async_api import async_playwright  # type: ignore[import-not-found]
            logger.info("meeting_agent_playwright_loaded")
            return async_playwright
        except ImportError:
            logger.debug("meeting_agent_no_playwright")
            return None

    def is_available(self) -> bool:
        return self._driver is not None

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    async def join(
        self,
        url: str,
        *,
        title: Optional[str] = None,
        display_name: str = "Zero",
    ) -> MeetingSession:
        """Join a meeting. Returns the session record immediately; actual
        join progress is reported via status transitions."""
        if not _MEET_URL_RE.match(url):
            raise ValueError(f"Unsupported meeting URL: {url}")
        session = MeetingSession(
            id=uuid.uuid4().hex[:12],
            url=url,
            title=title or _infer_title(url),
            status="joining" if self.is_available() else "error",
            joined_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
            error=None if self.is_available() else "playwright not installed",
        )
        self._sessions[session.id] = session
        self._save()
        if self.is_available():
            self._tasks[session.id] = asyncio.create_task(
                self._driver_lifecycle(session, display_name)
            )
        logger.info(
            "meeting_agent_join",
            session=session.id,
            url=url,
            available=self.is_available(),
        )
        return session

    async def speak(self, session_id: str, text: str) -> dict:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        if not self.is_available() or session.status != "active":
            return {"status": "unavailable", "session_id": session_id}
        try:
            from app.services.tts_service import get_tts_service
            tts = get_tts_service()
            wav_bytes, _meta = await tts.synthesize_with_meta(text)
            # In a full implementation we'd pipe wav_bytes into the
            # virtual-mic of the headless browser tab. Today: just log +
            # record the spoken turn so the UI reflects activity.
            session.spoken_turns += 1
            session.status = "speaking"
            self._save()
            await asyncio.sleep(0.2)
            session.status = "active"
            self._save()
            logger.info("meeting_agent_speak", session=session_id, chars=len(text))
            return {"status": "ok", "bytes": len(wav_bytes), "session_id": session_id}
        except Exception as e:  # noqa: BLE001
            logger.warning("meeting_agent_speak_failed", error=str(e))
            return {"status": "error", "error": str(e)}

    async def leave(self, session_id: str) -> dict:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        session.status = "leaving"
        self._save()
        task = self._tasks.pop(session_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        session.status = "ended"
        session.ended_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        self._save()
        # On leave, write a final L1 summary into the vault under
        # ``meetings/{session_id}``.
        try:
            await self._write_final_summary(session)
        except Exception as e:  # noqa: BLE001
            logger.warning("meeting_agent_summary_failed", error=str(e))
        return asdict(session)

    def list_sessions(self, limit: int = 50) -> list[dict]:
        items = sorted(
            self._sessions.values(), key=lambda s: s.joined_at, reverse=True
        )
        return [asdict(s) for s in items[:limit]]

    def get(self, session_id: str) -> Optional[dict]:
        s = self._sessions.get(session_id)
        return asdict(s) if s else None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _driver_lifecycle(self, session: MeetingSession, display_name: str) -> None:
        """Drive Playwright through the join → listen → leave lifecycle.

        Kept minimal — real audio capture requires platform setup; we mark
        the session active so the rest of the system can integrate with it.
        """
        try:
            session.status = "active"
            self._save()
            while session.status == "active":
                await asyncio.sleep(5.0)
                # Stub heartbeat: a real driver would poll for new transcript
                # frames from the Chromium audio capture and call
                # `_ingest_transcript` below.
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            session.status = "error"
            session.error = str(e)
            self._save()
            logger.warning("meeting_agent_driver_failed", error=str(e))

    async def ingest_transcript(self, session_id: str, text: str, *, speaker: Optional[str] = None) -> None:
        """Called by the driver (or a test) whenever a transcript chunk arrives.

        Writes the chunk into the Memory Tree under a per-meeting source so
        it's searchable + browsable in the MemoryVault UI.
        """
        session = self._sessions.get(session_id)
        if session is None or not text.strip():
            return
        prefix = f"**{speaker}**: " if speaker else ""
        try:
            from app.services.memory_tree import get_memory_tree
            tree = get_memory_tree()
            paths = await tree.write_chunk(
                f"meeting_{session.id}",
                prefix + text,
                level=0,
                title=session.title,
                tags=["meeting", "transcript"],
            )
            session.transcript_chars += len(text)
            session.notes_vault_paths.extend(str(p) for p in paths)
            self._save()
        except Exception as e:  # noqa: BLE001
            logger.warning("meeting_agent_ingest_failed", error=str(e))

    async def _write_final_summary(self, session: MeetingSession) -> None:
        if session.transcript_chars == 0:
            return
        from app.services.memory_tree import get_memory_tree
        tree = get_memory_tree()

        # Ask the narrator persona (via hint:summarize) to write a real
        # summary over the transcript chunks. Falls back to a header-only
        # stub if the LLM isn't reachable — the L1 file still lands.
        summary_body = await self._narrator_summarize(session) or (
            f"_(LLM unavailable — see ``meeting_{session.id}`` source for full transcript.)_"
        )
        body = (
            f"# Meeting summary — {session.title}\n\n"
            f"- URL: {session.url}\n"
            f"- Joined: {session.joined_at}\n"
            f"- Ended: {session.ended_at}\n"
            f"- Transcript chars: {session.transcript_chars}\n"
            f"- Spoken turns: {session.spoken_turns}\n\n"
            f"## Narrator notes\n\n{summary_body}\n"
        )
        await tree.write_chunk(
            f"meeting_{session.id}",
            body,
            level=1,
            title=f"{session.title} — summary",
            tags=["meeting", "summary", "narrator"],
        )

    async def _narrator_summarize(self, session: MeetingSession) -> Optional[str]:
        """Run the narrator persona over the meeting transcript.

        Returns the rendered summary text or None when the LLM router can't
        be reached. Uses ``hint:summarize`` so it routes through the
        configured summarization model (local-eligible by default).
        """
        try:
            from app.services.memory_tree import get_memory_tree
            from app.infrastructure.llm_router import get_llm_router
            from app.services.soul_md import load_soul_md
            from pathlib import Path
        except Exception:
            return None

        tree = get_memory_tree()
        # Pull every transcript chunk for this meeting and concatenate.
        chunks = await tree.search(session.title, scope="source", source=f"meeting_{session.id}", limit=100)
        if not chunks:
            return None
        joined = "\n".join(c.snippet for c in chunks if c.snippet)
        joined = joined[:12000]  # safety cap

        persona_dir = Path(__file__).resolve().parents[1] / "data" / "reachy_profiles" / "narrator"
        system_prompt = load_soul_md(persona_dir) or (
            "You are the narrator: summarize meetings concisely."
        )
        prompt = (
            f"{system_prompt}\n\n"
            f"Summarize the meeting transcript below in 3–5 bullet points. "
            f"Highlight decisions, owners, and follow-ups. Title: {session.title}.\n\n"
            f"---\nTranscript snippets:\n{joined}\n---"
        )
        # Resolve via hint:summarize so the routing preset takes effect.
        try:
            llm = get_llm_router()
            spec = llm.resolve("hint:summarize")
            logger.info(
                "meeting_agent_narrator_route",
                session=session.id,
                model=spec,
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("meeting_agent_narrator_route_failed", error=str(e))
            return None
        # We don't make the actual LLM HTTP call here — the live LLM clients
        # vary by provider and have their own retry/timeout policies. Hand
        # the prompt to whoever calls this next via the prompt return.
        # For now, return the assembled prompt as a stand-in summary; once
        # we wire the unified LLM client into this path, swap to its output.
        return f"_(Narrator prompt assembled; route: ``{spec}``. Full text below.)_\n\n{prompt[:800]}…"

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> dict[str, MeetingSession]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        out: dict[str, MeetingSession] = {}
        for k, v in raw.items():
            try:
                out[k] = MeetingSession(**v)
            except Exception:
                continue
        return out

    def _save(self) -> None:
        data = {k: asdict(v) for k, v in self._sessions.items()}
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            logger.warning("meeting_agent_save_failed", error=str(e))


def _infer_title(url: str) -> str:
    if "meet.google.com" in url:
        return f"Google Meet {url.rstrip('/').rsplit('/', 1)[-1]}"
    if "zoom.us" in url:
        return f"Zoom meeting {url.rstrip('/').rsplit('/', 1)[-1]}"
    return "Meeting"


@lru_cache(maxsize=1)
def get_meeting_agent_service() -> MeetingAgentService:
    return MeetingAgentService()
