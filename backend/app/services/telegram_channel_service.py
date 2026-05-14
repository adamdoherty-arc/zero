"""
Telegram 2-way messaging channel.

openhuman ships Telegram as its primary messaging channel â€” 80+ actions,
2-way, runs through user-encrypted credentials. Zero already has a Discord
bot; this module adds the Telegram counterpart.

Behavior:
  â€¢ If ``TELEGRAM_BOT_TOKEN`` is set, the service starts a long-poll loop
    that delivers inbound messages to a registered handler.
  â€¢ Outbound messages go through the Bot API (``sendMessage``).
  â€¢ No third-party SDK required â€” uses raw httpx against api.telegram.org.

Privacy: tokens never sit on disk. The service reads ``TELEGRAM_BOT_TOKEN``
from env at every poll, so rotating the token requires only a restart.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Awaitable, Callable, Optional

import structlog

logger = structlog.get_logger(__name__)


TELEGRAM_API = "https://api.telegram.org"
POLL_TIMEOUT_S = 25  # long-poll timeout
MAX_MESSAGE_LEN = 4096


@dataclass
class TelegramMessage:
    update_id: int
    chat_id: int
    user_id: int
    username: Optional[str]
    text: str
    date_ts: int


InboundHandler = Callable[[TelegramMessage], Awaitable[None]]


class TelegramChannelService:
    """Lightweight Bot-API client + long-poll loop."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._handler: Optional[InboundHandler] = None
        self._last_update_id = 0
        self._sent_count = 0
        self._received_count = 0
        self._last_error: Optional[str] = None

    # ------------------------------------------------------------------
    # Env-driven configuration
    # ------------------------------------------------------------------

    @property
    def token(self) -> Optional[str]:
        return os.getenv("TELEGRAM_BOT_TOKEN") or None

    def is_configured(self) -> bool:
        return bool(self.token)

    def set_handler(self, handler: InboundHandler) -> None:
        """Register an async callable that receives every inbound message.

        Default fan-out (when no handler is set): each message lands in the
        Memory Vault under ``sources/telegram/L0/``.
        """
        self._handler = handler

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        if not self.is_configured():
            logger.info("telegram_channel_skipped", reason="no_token")
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("telegram_channel_started")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None
        logger.info("telegram_channel_stopped")

    def status(self) -> dict:
        return {
            "configured": self.is_configured(),
            "running": self._running,
            "sent_count": self._sent_count,
            "received_count": self._received_count,
            "last_update_id": self._last_update_id,
            "last_error": self._last_error,
        }

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    async def send(self, chat_id: int, text: str, *, parse_mode: Optional[str] = None) -> dict:
        """Send a message to a chat. Returns the Bot API response dict."""
        token = self.token
        if not token:
            return {"ok": False, "error": "no token"}
        if not text:
            return {"ok": False, "error": "empty text"}
        if len(text) > MAX_MESSAGE_LEN:
            text = text[: MAX_MESSAGE_LEN - 3] + "â€¦"

        import httpx
        params = {"chat_id": chat_id, "text": text}
        if parse_mode:
            params["parse_mode"] = parse_mode
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{TELEGRAM_API}/bot{token}/sendMessage", json=params
                )
                data = resp.json()
                if data.get("ok"):
                    self._sent_count += 1
                else:
                    self._last_error = data.get("description")
                return data
        except Exception as e:  # noqa: BLE001
            self._last_error = str(e)
            return {"ok": False, "error": str(e)}

    # ------------------------------------------------------------------
    # Inbound long-poll
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        import httpx
        while self._running:
            token = self.token
            if not token:
                await asyncio.sleep(5.0)
                continue
            params = {
                "timeout": POLL_TIMEOUT_S,
                "offset": self._last_update_id + 1,
            }
            try:
                async with httpx.AsyncClient(timeout=POLL_TIMEOUT_S + 5) as client:
                    resp = await client.get(
                        f"{TELEGRAM_API}/bot{token}/getUpdates", params=params
                    )
                    data = resp.json()
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                self._last_error = str(e)
                await asyncio.sleep(3.0)
                continue
            if not data.get("ok"):
                self._last_error = data.get("description")
                await asyncio.sleep(3.0)
                continue
            for update in data.get("result", []) or []:
                try:
                    await self._dispatch(update)
                except Exception as e:  # noqa: BLE001
                    logger.warning("telegram_dispatch_failed", error=str(e))

    async def _dispatch(self, update: dict) -> None:
        update_id = int(update.get("update_id", 0))
        if update_id > self._last_update_id:
            self._last_update_id = update_id
        msg = update.get("message") or update.get("edited_message")
        if not msg or "text" not in msg:
            return
        chat = msg.get("chat") or {}
        sender = msg.get("from") or {}
        message = TelegramMessage(
            update_id=update_id,
            chat_id=int(chat.get("id", 0)),
            user_id=int(sender.get("id", 0)),
            username=sender.get("username") or sender.get("first_name"),
            text=str(msg.get("text", "")),
            date_ts=int(msg.get("date", 0)),
        )
        self._received_count += 1
        handler = self._handler or self._default_handler
        await handler(message)

    async def _default_handler(self, message: TelegramMessage) -> None:
        """When no custom handler is set, write the message to the vault."""
        try:
            from app.services.memory_tree import get_memory_tree
            tree = get_memory_tree()
            await tree.write_chunk(
                "telegram",
                f"**@{message.username or message.user_id}** "
                f"(chat {message.chat_id}): {message.text}",
                level=0,
                title=f"Telegram message {message.update_id}",
                tags=["telegram", "inbound"],
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("telegram_default_handler_failed", error=str(e))


@lru_cache(maxsize=1)
def get_telegram_channel_service() -> TelegramChannelService:
    return TelegramChannelService()
