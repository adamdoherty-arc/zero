"""
Zero Discord Bot — lightweight discord.py bot connected to Claude Agent SDK.

Replaces the OpenClaw gateway for Discord messaging. Receives messages,
processes them through the messaging bridge (Claude + MCP tools), and
sends responses back.

Run standalone: python -m app.services.discord_bot
Or start from main.py as a background task.

Environment variables:
  DISCORD_BOT_TOKEN             - Discord bot token
  DISCORD_USER_ID               - Allowed user ID (Adam)
  DISCORD_GUILD_ID              - Server/guild ID
  DISCORD_NOTIFICATION_CHANNEL_ID - Channel for proactive notifications
"""

import asyncio
import os
import sys
from pathlib import Path

import discord
import structlog

# Add project root to path for imports
_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from app.services.messaging_bridge import process_message, split_message

logger = structlog.get_logger(__name__)

# Load .env if running standalone
def _load_dotenv():
    env_path = Path(__file__).parent.parent.parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not os.getenv(key):
            os.environ[key] = value

_load_dotenv()

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")


def _env_int(name: str) -> int:
    raw = (os.getenv(name) or "").strip()
    return int(raw) if raw else 0


ALLOWED_USER_ID = _env_int("DISCORD_USER_ID")
GUILD_ID = _env_int("DISCORD_GUILD_ID")
NOTIFICATION_CHANNEL_ID = _env_int("DISCORD_NOTIFICATION_CHANNEL_ID")

# Discord intents
intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True

client = discord.Client(intents=intents)

# Track processing to avoid duplicate responses
_processing: set[int] = set()


@client.event
async def on_ready():
    logger.info("discord_bot_ready", user=str(client.user), guild_count=len(client.guilds))
    if NOTIFICATION_CHANNEL_ID:
        channel = client.get_channel(NOTIFICATION_CHANNEL_ID)
        if channel:
            await channel.send("**Zero** is online. (Claude-powered)")


@client.event
async def on_message(message: discord.Message):
    # Ignore own messages
    if message.author == client.user:
        return

    # Ignore bots
    if message.author.bot:
        return

    # Check if message is from allowed user (DMs or mentions)
    is_dm = isinstance(message.channel, discord.DMChannel)
    is_mentioned = client.user in message.mentions if client.user else False
    is_allowed_user = message.author.id == ALLOWED_USER_ID

    # In DMs: only respond to allowed user
    # In servers: respond to mentions from allowed user, or in specific channels
    if is_dm and not is_allowed_user:
        return

    if not is_dm and not is_mentioned and not is_allowed_user:
        return

    # Strip bot mention from message text
    content = message.content
    if client.user:
        content = content.replace(f"<@{client.user.id}>", "").strip()
        content = content.replace(f"<@!{client.user.id}>", "").strip()

    if not content:
        return

    # Avoid duplicate processing
    if message.id in _processing:
        return
    _processing.add(message.id)

    try:
        # Show typing indicator while processing
        async with message.channel.typing():
            logger.info(
                "discord_message_received",
                author=str(message.author),
                channel=str(message.channel),
                content_preview=content[:100],
            )

            response = await process_message(
                message=content,
                channel="discord",
                sender_id=str(message.author.id),
                thread_id=f"discord-{message.author.id}",
            )

            # Split and send response
            chunks = split_message(response, max_length=1900)
            for chunk in chunks:
                if is_dm:
                    await message.channel.send(chunk)
                else:
                    await message.reply(chunk, mention_author=False)

    except discord.HTTPException as e:
        logger.error("discord_send_error", error=str(e))
    except Exception as e:
        logger.error("discord_processing_error", error=str(e))
        try:
            await message.channel.send("Sorry, hit an error processing that.")
        except Exception:
            pass
    finally:
        _processing.discard(message.id)


async def send_notification(channel_id: int, content: str):
    """Send a proactive notification to a Discord channel."""
    channel = client.get_channel(channel_id)
    if channel:
        chunks = split_message(content, max_length=1900)
        for chunk in chunks:
            await channel.send(chunk)


async def start_bot():
    """Start the Discord bot (call from asyncio context)."""
    if not BOT_TOKEN:
        logger.warning("discord_bot_disabled", reason="DISCORD_BOT_TOKEN not set")
        return

    logger.info("discord_bot_starting")
    await client.start(BOT_TOKEN)


async def stop_bot():
    """Gracefully stop the Discord bot."""
    if client.is_ready():
        await client.close()
        logger.info("discord_bot_stopped")


def run_standalone():
    """Run the bot as a standalone process."""
    if not BOT_TOKEN:
        print("ERROR: DISCORD_BOT_TOKEN not set in environment or .env")
        sys.exit(1)

    print(f"Starting Zero Discord bot...")
    print(f"  Allowed user: {ALLOWED_USER_ID}")
    print(f"  Guild: {GUILD_ID}")
    print(f"  Notification channel: {NOTIFICATION_CHANNEL_ID}")

    client.run(BOT_TOKEN)


if __name__ == "__main__":
    run_standalone()
