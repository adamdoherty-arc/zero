"""
Email voice triage session — finite state machine.

Owns the queue of unread emails awaiting voice triage and the conversational
state for the currently-prompted email. The scheduler enqueues; the Reachy
intent router asks `handle_user_intent`; the session emits prompts via
`reachy.say` (announcement voice) and reads bodies via `reachy.say` with the
email-reader voice override.

Single-user system, single Reachy. One session is enough — keep it in-memory.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Literal, Optional

import structlog

from app.services.voice_intent_router import Intent

logger = structlog.get_logger(__name__)


SessionState = Literal[
    "idle",
    "awaiting_decision",
    "awaiting_post_read_action",
    "composing_reply",
    "awaiting_send_confirmation",
]


# Default voice for reading email content. Distinct from the announcement voice
# (configured via TTS_EDGE_VOICE elsewhere) so the user clearly hears the swap.
DEFAULT_READER_VOICE = os.getenv("ZERO_REACHY_EMAIL_READER_VOICE", "en-GB-RyanNeural")

# Per-state timeout. After this many seconds with no input, revert to idle.
STATE_TIMEOUT_SECONDS = 60.0

# Soft cap on body characters spoken aloud. Longer bodies are summarised.
BODY_SPEAK_CAP = 600

# Allowed intents per state. The intent router gets only these as candidates.
ALLOWED_INTENTS: dict[SessionState, list[Intent]] = {
    "idle": [],
    "awaiting_decision": ["read", "ignore", "delete", "respond", "skip", "stop"],
    "awaiting_post_read_action": ["delete", "respond", "skip", "stop", "ignore"],
    "composing_reply": ["cancel", "stop"],
    "awaiting_send_confirmation": ["send", "cancel", "stop"],
}


@dataclass
class _SessionContext:
    """Per-active-email context. Reset on each new email or back to idle."""

    email_id: Optional[str] = None
    sender_label: Optional[str] = None
    subject: Optional[str] = None
    in_reply_to_message_id: Optional[str] = None
    thread_id: Optional[str] = None
    sender_email: Optional[str] = None
    pending_draft: Optional[str] = None
    pending_reply_to: Optional[str] = None
    pending_subject: Optional[str] = None
    last_state_change: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class EmailVoiceSessionService:
    """In-memory state machine for email voice triage."""

    def __init__(self) -> None:
        self._state: SessionState = "idle"
        self._queue: list[str] = []  # email_ids awaiting triage
        self._ctx = _SessionContext()
        self._lock = asyncio.Lock()
        self._reader_voice = DEFAULT_READER_VOICE

    # -- Public API used by scheduler / router --

    def is_active(self) -> bool:
        """True if a triage session is currently in flight (non-idle)."""
        return self._state != "idle"

    def state(self) -> SessionState:
        return self._state

    def allowed_intents(self) -> list[Intent]:
        return list(ALLOWED_INTENTS.get(self._state, []))

    def status(self) -> dict:
        return {
            "state": self._state,
            "queue_length": len(self._queue),
            "active_email_id": self._ctx.email_id,
            "active_sender": self._ctx.sender_label,
            "active_subject": self._ctx.subject,
            "reader_voice": self._reader_voice,
            "last_state_change": self._ctx.last_state_change.isoformat(),
        }

    async def enqueue(self, email_ids: list[str]) -> int:
        """Push newly arrived email ids onto the triage queue. Returns added count."""
        async with self._lock:
            added = 0
            for eid in email_ids:
                if eid not in self._queue and eid != self._ctx.email_id:
                    self._queue.append(eid)
                    added += 1
            return added

    async def kickstart_if_idle(self) -> Optional[str]:
        """If idle and the queue has items, announce the next one. Returns the email_id announced."""
        # Auto-revert to idle if a state has been stuck too long (timeout).
        await self._maybe_timeout()
        async with self._lock:
            if self._state != "idle":
                return None
            if not self._queue:
                return None
            email_id = self._queue.pop(0)
        await self._announce_email(email_id)
        return email_id

    async def handle_user_intent(self, intent: Intent, raw_text: str = "") -> dict:
        """Drive the FSM based on a classified intent. Returns a small status dict."""
        await self._maybe_timeout()
        if intent == "stop":
            await self._reset_to_idle(reason="user_stop")
            await self._say("Stopped.")
            return {"handled": True, "next_state": self._state}

        if self._state == "awaiting_decision":
            return await self._on_awaiting_decision(intent, raw_text)
        if self._state == "awaiting_post_read_action":
            return await self._on_awaiting_post_read(intent, raw_text)
        if self._state == "composing_reply":
            return await self._on_composing_reply(intent, raw_text)
        if self._state == "awaiting_send_confirmation":
            return await self._on_send_confirmation(intent, raw_text)
        return {"handled": False, "reason": f"no active state ({self._state})"}

    async def submit_reply_text(self, text: str) -> dict:
        """User dictated the substance of their reply. Draft, read back, await confirm."""
        if self._state != "composing_reply":
            return {"handled": False, "reason": f"not composing ({self._state})"}
        if not text or not text.strip():
            await self._say("I didn't catch that. What would you like to say?")
            return {"handled": False, "reason": "empty"}

        try:
            from app.services.email_draft_service import get_email_draft_service

            draft_service = get_email_draft_service()
            result = await draft_service.draft_reply(
                email_id=self._ctx.email_id,
                intent="reply",
                tone="professional",
                key_points=[text.strip()],
            )
            if result.get("error") or not result.get("draft"):
                await self._say("I couldn't draft that. Cancelled.")
                await self._next_or_idle()
                return {"handled": False, "error": result.get("error")}
            self._ctx.pending_draft = result["draft"]
            self._ctx.pending_reply_to = result.get("to") or self._ctx.sender_email
            self._ctx.pending_subject = result.get("subject") or self._ctx.subject
        except Exception as e:
            logger.error("draft_reply_failed", error=str(e))
            await self._say("I couldn't draft that. Cancelled.")
            await self._next_or_idle()
            return {"handled": False, "error": str(e)}

        await self._set_state("awaiting_send_confirmation")
        intro = "Here's the draft."
        await self._say(intro)
        await self._say(self._ctx.pending_draft, voice_override=self._reader_voice)
        await self._say("Say send, or cancel.")
        return {"handled": True, "next_state": self._state, "draft": self._ctx.pending_draft}

    # -- State handlers --

    async def _on_awaiting_decision(self, intent: Intent, raw_text: str) -> dict:
        if intent == "read":
            await self._read_active_email()
            return {"handled": True, "next_state": self._state}
        if intent in ("ignore", "skip"):
            await self._archive_active_email()
            await self._next_or_idle()
            return {"handled": True, "next_state": self._state}
        if intent == "delete":
            await self._trash_active_email()
            await self._next_or_idle()
            return {"handled": True, "next_state": self._state}
        if intent == "respond":
            await self._set_state("composing_reply")
            await self._say("Okay. What would you like to say?")
            return {"handled": True, "next_state": self._state}
        await self._say("I didn't catch that. Read or ignore?")
        return {"handled": False, "reason": "ambiguous"}

    async def _on_awaiting_post_read(self, intent: Intent, raw_text: str) -> dict:
        if intent == "delete":
            await self._trash_active_email()
            await self._next_or_idle()
            return {"handled": True, "next_state": self._state}
        if intent == "respond":
            await self._set_state("composing_reply")
            await self._say("Okay. What would you like to say?")
            return {"handled": True, "next_state": self._state}
        if intent in ("skip", "ignore"):
            await self._mark_read_active_email()
            await self._next_or_idle()
            return {"handled": True, "next_state": self._state}
        await self._say("Delete, respond, or next?")
        return {"handled": False, "reason": "ambiguous"}

    async def _on_composing_reply(self, intent: Intent, raw_text: str) -> dict:
        if intent == "cancel":
            await self._say("Cancelled.")
            await self._next_or_idle()
            return {"handled": True, "next_state": self._state}
        # Treat the raw text as the reply substance.
        return await self.submit_reply_text(raw_text)

    async def _on_send_confirmation(self, intent: Intent, raw_text: str) -> dict:
        if intent == "send":
            sent_id = await self._send_pending_reply()
            if sent_id:
                await self._say("Sent.")
            else:
                await self._say("Send failed. The draft is still pending.")
            await self._next_or_idle()
            return {"handled": True, "next_state": self._state, "sent_id": sent_id}
        if intent == "cancel":
            await self._say("Cancelled.")
            self._ctx.pending_draft = None
            await self._next_or_idle()
            return {"handled": True, "next_state": self._state}
        await self._say("Say send, or cancel.")
        return {"handled": False, "reason": "ambiguous"}

    # -- Email actions --

    async def _announce_email(self, email_id: str) -> None:
        try:
            from app.services.gmail_service import get_gmail_service

            gmail = get_gmail_service()
            email = await gmail.get_email(email_id)
        except Exception as e:
            logger.warning("email_lookup_failed", email_id=email_id, error=str(e))
            email = None

        if not email:
            logger.warning("email_not_found_skipping", email_id=email_id)
            await self._next_or_idle()
            return

        sender_label = (
            (email.from_address.name or email.from_address.email)
            if email.from_address
            else "an unknown sender"
        )
        subject = (email.subject or "no subject").strip()

        self._ctx = _SessionContext(
            email_id=email_id,
            sender_label=sender_label,
            sender_email=email.from_address.email if email.from_address else None,
            subject=subject,
            thread_id=email.thread_id,
            in_reply_to_message_id=self._extract_rfc_message_id(email),
        )
        await self._set_state("awaiting_decision")
        await self._say(
            f"New email from {sender_label}. Subject: {subject}. Read or ignore?"
        )

    async def _read_active_email(self) -> None:
        try:
            from app.services.gmail_service import get_gmail_service

            gmail = get_gmail_service()
            email = await gmail.get_email(self._ctx.email_id) if self._ctx.email_id else None
        except Exception:
            email = None
        if not email:
            await self._say("I couldn't fetch the body.")
            await self._next_or_idle()
            return

        body = (email.body_text or email.snippet or "").strip()
        if not body:
            await self._say("This email has no readable body.")
        else:
            spoken = await self._prepare_body_for_speech(body)
            await self._say(spoken, voice_override=self._reader_voice)

        await self._set_state("awaiting_post_read_action")
        await self._say("Delete, respond, or next?")

    async def _archive_active_email(self) -> None:
        if not self._ctx.email_id:
            return
        try:
            from app.services.gmail_service import get_gmail_service

            await get_gmail_service().archive_email(self._ctx.email_id)
            logger.info("voice_triage_archived", email_id=self._ctx.email_id)
        except Exception as e:
            logger.warning("voice_triage_archive_failed", error=str(e))

    async def _trash_active_email(self) -> None:
        if not self._ctx.email_id:
            return
        try:
            from app.services.gmail_service import get_gmail_service

            await get_gmail_service().trash_email(self._ctx.email_id)
            logger.info("voice_triage_trashed", email_id=self._ctx.email_id)
        except Exception as e:
            logger.warning("voice_triage_trash_failed", error=str(e))

    async def _mark_read_active_email(self) -> None:
        if not self._ctx.email_id:
            return
        try:
            from app.services.gmail_service import get_gmail_service

            await get_gmail_service().mark_as_read(self._ctx.email_id)
        except Exception as e:
            logger.debug("voice_triage_mark_read_failed", error=str(e))

    async def _send_pending_reply(self) -> Optional[str]:
        if not self._ctx.pending_draft or not self._ctx.pending_reply_to:
            return None
        try:
            from app.services.gmail_service import get_gmail_service

            sent_id = await get_gmail_service().send_email(
                to=self._ctx.pending_reply_to,
                subject=self._ctx.pending_subject or self._ctx.subject or "(no subject)",
                body_text=self._ctx.pending_draft,
                in_reply_to=self._ctx.in_reply_to_message_id,
                thread_id=self._ctx.thread_id,
            )
            if sent_id and self._ctx.email_id:
                # Mark the original as read so it doesn't re-prompt.
                await self._mark_read_active_email()
            return sent_id
        except Exception as e:
            logger.error("voice_triage_send_failed", error=str(e))
            return None

    # -- Helpers --

    async def _say(self, text: str, *, voice_override: Optional[str] = None) -> None:
        try:
            from app.services.reachy_service import get_reachy_service

            reachy = get_reachy_service()
            if not await reachy.is_connected():
                logger.debug("reachy_unreachable_skipping_say", text=text[:60])
                return
            await reachy.say(text, voice_override=voice_override)
        except Exception as e:
            logger.debug("voice_session_say_failed", error=str(e))

    async def _set_state(self, new_state: SessionState) -> None:
        async with self._lock:
            self._state = new_state
            self._ctx.last_state_change = datetime.now(timezone.utc)
        logger.info("email_voice_state", state=new_state, email_id=self._ctx.email_id)

    async def _reset_to_idle(self, *, reason: str) -> None:
        async with self._lock:
            self._state = "idle"
            self._ctx = _SessionContext()
        logger.info("email_voice_reset", reason=reason)

    async def _next_or_idle(self) -> None:
        """Announce the next queued email, or revert to idle if the queue is empty."""
        next_id: Optional[str] = None
        async with self._lock:
            self._ctx = _SessionContext()
            if self._queue:
                next_id = self._queue.pop(0)
            else:
                self._state = "idle"
        if next_id:
            await self._announce_email(next_id)

    async def _maybe_timeout(self) -> None:
        if self._state == "idle":
            return
        elapsed = (datetime.now(timezone.utc) - self._ctx.last_state_change).total_seconds()
        if elapsed > STATE_TIMEOUT_SECONDS:
            logger.info("email_voice_state_timeout", state=self._state, elapsed=elapsed)
            await self._reset_to_idle(reason="timeout")

    async def _prepare_body_for_speech(self, body: str) -> str:
        """Return body suitable for TTS: trim whitespace, summarise if over the cap."""
        body = body.strip()
        if len(body) <= BODY_SPEAK_CAP:
            return body
        # Summarise long bodies via the unified LLM client. Failure → truncated body.
        try:
            from app.infrastructure.unified_llm_client import get_unified_llm_client

            client = get_unified_llm_client()
            prompt = (
                "Summarise the following email body for a voice assistant to read aloud. "
                "Keep it under 4 short sentences. Plain prose, no bullets, no headers.\n\n"
                f"{body[:4000]}"
            )
            summary = await client.chat(
                prompt=prompt,
                task_type="summarize",
                temperature=0.2,
                max_tokens=180,
            )
            if isinstance(summary, dict):
                summary = summary.get("content") or summary.get("response") or ""
            text = str(summary).strip()
            if text:
                return text
        except Exception as e:
            logger.debug("body_summarise_failed", error=str(e))
        return body[:BODY_SPEAK_CAP] + "..."

    @staticmethod
    def _extract_rfc_message_id(email) -> Optional[str]:
        """Pull the RFC 2822 Message-ID from cached headers if present.

        EmailCacheModel stores Gmail's id (used for thread mapping) but the
        In-Reply-To/References headers need the RFC Message-ID, which we don't
        currently persist. Return None — Gmail will still thread via threadId,
        which we do persist. Keep the hook for when we cache headers.
        """
        return None


@lru_cache()
def get_email_voice_session_service() -> EmailVoiceSessionService:
    return EmailVoiceSessionService()
