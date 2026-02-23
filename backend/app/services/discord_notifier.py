"""
Discord notification service for Zero.

Sends messages directly to a Discord channel via the Discord REST API,
bypassing the OpenClaw gateway for reliable proactive notifications
(briefings, alerts, digests).
"""

import os
from functools import lru_cache
from typing import Any, Dict, List, Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)

DISCORD_API = "https://discord.com/api/v10"
MAX_MESSAGE_LENGTH = 2000


class DiscordNotifier:
    """Send messages and embeds to Discord channels via REST API."""

    def __init__(self):
        self._token = os.getenv("DISCORD_BOT_TOKEN", "")
        self._default_channel = os.getenv("DISCORD_NOTIFICATION_CHANNEL_ID", "")

    @property
    def configured(self) -> bool:
        return bool(self._token and self._default_channel)

    async def send(self, content: str, channel_id: Optional[str] = None) -> bool:
        """Send a plain text message to a Discord channel.

        Args:
            content: Message text (auto-truncated to 2000 chars).
            channel_id: Target channel. Defaults to DISCORD_NOTIFICATION_CHANNEL_ID.

        Returns:
            True if sent successfully.
        """
        target = channel_id or self._default_channel
        if not target or not self._token:
            logger.warning("discord_notifier_not_configured",
                           has_token=bool(self._token), has_channel=bool(target))
            return False

        # Truncate to Discord's limit
        if len(content) > MAX_MESSAGE_LENGTH:
            content = content[:MAX_MESSAGE_LENGTH - 4] + "..."

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{DISCORD_API}/channels/{target}/messages",
                    json={"content": content},
                    headers={
                        "Authorization": f"Bot {self._token}",
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code < 400:
                    logger.info("discord_message_sent", channel=target,
                                length=len(content))
                    return True
                else:
                    logger.warning("discord_send_failed", status=resp.status_code,
                                   body=resp.text[:200])
                    return False
        except Exception as e:
            logger.error("discord_send_error", error=str(e))
            return False

    async def send_embed(
        self,
        title: str,
        description: str,
        fields: Optional[List[Dict[str, Any]]] = None,
        color: int = 0x5865F2,
        channel_id: Optional[str] = None,
    ) -> bool:
        """Send a rich embed to a Discord channel.

        Args:
            title: Embed title.
            description: Embed description (up to 4096 chars).
            fields: List of {"name": str, "value": str, "inline": bool}.
            color: Embed sidebar color (default: Discord blurple).
            channel_id: Target channel. Defaults to DISCORD_NOTIFICATION_CHANNEL_ID.

        Returns:
            True if sent successfully.
        """
        target = channel_id or self._default_channel
        if not target or not self._token:
            logger.warning("discord_notifier_not_configured")
            return False

        embed: Dict[str, Any] = {
            "title": title[:256],
            "description": description[:4096],
            "color": color,
        }
        if fields:
            embed["fields"] = [
                {
                    "name": f["name"][:256],
                    "value": f["value"][:1024],
                    "inline": f.get("inline", False),
                }
                for f in fields[:25]  # Discord limit: 25 fields
            ]

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{DISCORD_API}/channels/{target}/messages",
                    json={"embeds": [embed]},
                    headers={
                        "Authorization": f"Bot {self._token}",
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code < 400:
                    logger.info("discord_embed_sent", channel=target, title=title)
                    return True
                else:
                    logger.warning("discord_embed_failed", status=resp.status_code,
                                   body=resp.text[:200])
                    return False
        except Exception as e:
            logger.error("discord_embed_error", error=str(e))
            return False


@lru_cache()
def get_discord_notifier() -> DiscordNotifier:
    """Get singleton DiscordNotifier instance."""
    return DiscordNotifier()
