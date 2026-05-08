"""
Messaging Bridge — connects chat channels to Claude Agent SDK.

Receives messages from Discord/WhatsApp, processes them through Claude
with Zero's MCP tools and personality, and returns responses.

Uses Claude Agent SDK (API credits) with:
- zero-api MCP server (Zero backend tools)
- kimi-llm MCP server (cheap LLM delegation)
- Zero persona system prompt
"""

import asyncio
import os
import structlog
from pathlib import Path
from typing import AsyncIterator

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ResultMessage,
    query,
)

logger = structlog.get_logger(__name__)


def _find_project_root() -> Path:
    """Find project root, handling both host and Docker contexts."""
    # In Docker: /app/app/services/messaging_bridge.py → /app has mcp_servers/
    # On host:   .../backend/app/services/messaging_bridge.py → .../zero has mcp_servers/
    for levels in (3, 4):  # Try 3 levels (Docker), then 4 levels (host)
        candidate = Path(__file__)
        for _ in range(levels):
            candidate = candidate.parent
        if (candidate / "mcp_servers").exists():
            return candidate
    # Fallback
    return Path(__file__).parent.parent.parent.parent


PROJECT_ROOT = _find_project_root()

# Only load zero-api and kimi-llm for the messaging bridge (not playwright/qmd/memory)
BRIDGE_MCP_SERVERS = {
    "zero-api": {
        "command": "python",
        "args": [str(PROJECT_ROOT / "mcp_servers" / "zero_api_mcp.py")],
    },
    "kimi-llm": {
        "command": "python",
        "args": [str(PROJECT_ROOT / "mcp_servers" / "kimi_mcp.py")],
    },
}

SYSTEM_PROMPT = """You are Zero, Adam's personal AI assistant.

## Identity
- Name: Zero
- Role: Digital familiar — part assistant, part second brain, part ops center
- Vibe: Sharp, efficient, slightly dry. Gets things done with minimal fuss.

## Personality
- Be genuinely helpful, not performatively helpful. Skip filler words.
- Have opinions. Disagree, prefer things, find stuff amusing or boring.
- Be resourceful before asking. Use tools to find answers.
- Concise: 1-3 sentences when possible. Elaborate only when data warrants it.

## Tools
You have MCP tools connected to Zero's backend system with real data:
- zero-api tools: sprints, tasks, email, calendar, knowledge, research, system status
- kimi-llm tools: cheap LLM for classification, summarization, analysis (use to save cost)

For domain questions (sprints, email, calendar, tasks, etc.), ALWAYS use zero-api tools.
For simple LLM tasks (classify, summarize), delegate to kimi-llm to save cost.
For casual chat, greetings, or general knowledge, answer directly.

## Response Format
{format_instructions}
"""

DISCORD_FORMAT = """Format for Discord:
- Use **bold** for emphasis (double asterisks)
- No ## headers — use **bold text** instead
- No markdown tables — use bullet lists
- Keep responses under 1500 characters when possible
- Use emoji sparingly for tone"""

WHATSAPP_FORMAT = """Format for WhatsApp:
- Use *bold* (single asterisks, NOT double)
- No headers (#) — use *BOLD CAPS* instead
- No markdown tables — use bullet lists
- Mobile-first, clean text"""

TERMINAL_FORMAT = """Format for terminal/CLI:
- Use standard markdown formatting
- Be concise but complete"""

REACHY_FORMAT = """Format for the Reachy Mini voice surface:
- This response will be spoken aloud by a TTS voice, not read on a screen.
- Plain spoken English only: no markdown, no asterisks, no bullets, no code, no URLs, no emoji.
- Keep it to 1-3 short sentences. Under 200 characters total when possible.
- Write numbers, times, dates in a natural spoken form ('three p.m.', 'two unread emails', 'April twenty-first').
- Prefer direct action confirmations over status dumps."""


def _get_format_instructions(channel: str) -> str:
    if channel == "discord":
        return DISCORD_FORMAT
    elif channel == "whatsapp":
        return WHATSAPP_FORMAT
    elif channel == "reachy":
        return REACHY_FORMAT
    return TERMINAL_FORMAT


async def process_message(
    message: str,
    channel: str = "discord",
    sender_id: str = "unknown",
    thread_id: str | None = None,
) -> str:
    """
    Process a user message through Claude Agent SDK.

    Args:
        message: The user's message text
        channel: Message source (discord, whatsapp, terminal)
        sender_id: Unique sender identifier
        thread_id: Optional conversation thread ID for continuity

    Returns:
        Claude's response text
    """
    if not thread_id:
        thread_id = f"{channel}-{sender_id}"

    format_instructions = _get_format_instructions(channel)
    system_prompt = SYSTEM_PROMPT.format(format_instructions=format_instructions)

    options = ClaudeAgentOptions(
        model="claude-haiku-4-5-20251001",
        system_prompt=system_prompt,
        mcp_servers=BRIDGE_MCP_SERVERS,
        allowed_tools=[
            "mcp__zero-api__*",
            "mcp__kimi-llm__*",
        ],
        permission_mode="bypassPermissions",
        max_turns=10,
        cwd=str(PROJECT_ROOT),
    )

    response_text = ""

    try:
        async for msg in query(prompt=message, options=options):
            if isinstance(msg, ResultMessage):
                if msg.subtype == "success":
                    response_text = msg.result or ""
                    logger.info(
                        "claude_response",
                        channel=channel,
                        sender_id=sender_id,
                        thread_id=thread_id,
                        cost_usd=getattr(msg, "total_cost_usd", None),
                        num_turns=getattr(msg, "num_turns", None),
                    )
                else:
                    error = getattr(msg, "error", "Unknown error")
                    logger.error("claude_error", error=error, channel=channel)
                    response_text = "Sorry, I hit an issue processing that. Try again?"

    except Exception as e:
        logger.error("bridge_error", error=str(e), channel=channel, sender_id=sender_id)
        response_text = f"Bridge error: {type(e).__name__}. Backend may be unreachable."

    return response_text or "No response generated."


def split_message(text: str, max_length: int = 1500) -> list[str]:
    """Split a long message into chunks for Discord/WhatsApp delivery."""
    if len(text) <= max_length:
        return [text]

    chunks = []
    current = ""

    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_length:
            if current:
                chunks.append(current.rstrip())
            current = line + "\n"
        else:
            current += line + "\n"

    if current.strip():
        chunks.append(current.rstrip())

    return chunks or [text[:max_length]]
