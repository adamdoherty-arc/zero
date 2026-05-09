"""
Kimi LLM MCP Server — exposes Kimi/Moonshot AI as LLM tools.

Claude can delegate classification, summarization, chat, and analysis
tasks to Kimi K2.6 ($0.95/$4.00 per 1M tokens).

Environment variables:
  KIMI_API_KEY  - Moonshot AI API key
  KIMI_BASE_URL - API base URL (default: https://api.moonshot.ai/v1)
"""

import json
import os
from pathlib import Path
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types


def _load_dotenv():
    """Load .env from project root (no dependency needed)."""
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not os.getenv(key):  # Don't override existing env vars
            os.environ[key] = value


_load_dotenv()

server = Server("kimi-llm")

API_KEY = os.getenv("KIMI_API_KEY", "") or os.getenv("ZERO_KIMI_API_KEY", "")
BASE_URL = os.getenv("KIMI_BASE_URL", "") or os.getenv("ZERO_KIMI_BASE_URL", "https://api.moonshot.ai/v1")


async def _kimi_chat(
    messages: list[dict[str, str]],
    model: str = "kimi-k2.6",
    temperature: float = 0.3,
    max_tokens: int = 2048,
    json_mode: bool = False,
) -> str:
    """Call Kimi API and return response text."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
        resp = await client.post(
            f"{BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    content = data["choices"][0]["message"].get("content", "")
    if not content:
        content = data["choices"][0]["message"].get("reasoning_content", "")

    return content


TOOLS = [
    types.Tool(
        name="kimi_chat",
        description="Send a chat message to Kimi for general conversation or Q&A. Uses kimi-k2.6 ($0.95/$4.00 per 1M tokens).",
        inputSchema={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "The message to send"},
                "system_prompt": {"type": "string", "description": "Optional system prompt for context"},
            },
            "required": ["message"],
        },
    ),
    types.Tool(
        name="kimi_classify",
        description="Classify text into categories using Kimi K2.6.",
        inputSchema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to classify"},
                "categories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of possible categories",
                },
                "instructions": {"type": "string", "description": "Additional classification instructions"},
            },
            "required": ["text", "categories"],
        },
    ),
    types.Tool(
        name="kimi_summarize",
        description="Summarize text using Kimi K2.6. Good for condensing long content.",
        inputSchema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to summarize"},
                "max_length": {"type": "string", "description": "Target length: brief, medium, detailed (default: medium)"},
                "style": {"type": "string", "description": "Style: bullet_points, paragraph, executive (default: paragraph)"},
            },
            "required": ["text"],
        },
    ),
    types.Tool(
        name="kimi_analyze",
        description="Deep analysis using Kimi K2.6 ($0.95/$4.00 per 1M tokens). Use for complex reasoning tasks where Claude delegation saves context window.",
        inputSchema={
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Analysis prompt"},
                "context": {"type": "string", "description": "Context data to analyze"},
            },
            "required": ["prompt"],
        },
    ),
    types.Tool(
        name="kimi_extract_json",
        description="Extract structured JSON from text using Kimi. Returns valid JSON matching the specified schema.",
        inputSchema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to extract data from"},
                "schema_description": {"type": "string", "description": "Description of the JSON schema to extract"},
                "example": {"type": "string", "description": "Example of expected JSON output"},
            },
            "required": ["text", "schema_description"],
        },
    ),
]


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[types.TextContent]:
    args = arguments or {}

    if not API_KEY:
        return [types.TextContent(type="text", text="Error: KIMI_API_KEY not configured")]

    try:
        if name == "kimi_chat":
            messages = []
            if "system_prompt" in args:
                messages.append({"role": "system", "content": args["system_prompt"]})
            messages.append({"role": "user", "content": args["message"]})
            result = await _kimi_chat(messages)

        elif name == "kimi_classify":
            categories_str = ", ".join(args["categories"])
            instructions = args.get("instructions", "")
            system = (
                f"You are a text classifier. Classify the given text into exactly one of these categories: {categories_str}. "
                f"Respond with ONLY the category name, nothing else. {instructions}"
            )
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": args["text"]},
            ]
            result = await _kimi_chat(messages, temperature=0.0, max_tokens=50)

        elif name == "kimi_summarize":
            max_length = args.get("max_length", "medium")
            style = args.get("style", "paragraph")
            length_map = {"brief": "2-3 sentences", "medium": "1 paragraph", "detailed": "2-3 paragraphs"}
            system = (
                f"Summarize the following text in {length_map.get(max_length, '1 paragraph')} "
                f"using {style} format. Be concise and capture key points."
            )
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": args["text"]},
            ]
            result = await _kimi_chat(messages)

        elif name == "kimi_analyze":
            messages = [{"role": "user", "content": args["prompt"]}]
            if "context" in args:
                messages[0]["content"] = f"Context:\n{args['context']}\n\nAnalysis task:\n{args['prompt']}"
            result = await _kimi_chat(messages, max_tokens=4096)

        elif name == "kimi_extract_json":
            example_str = f"\nExample output:\n{args['example']}" if "example" in args else ""
            system = (
                f"Extract data from the text and return ONLY valid JSON matching this schema: {args['schema_description']}. "
                f"No markdown, no explanation, just the JSON object.{example_str}"
            )
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": args["text"]},
            ]
            result = await _kimi_chat(messages, json_mode=True)

        else:
            return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

        return [types.TextContent(type="text", text=result)]

    except httpx.HTTPStatusError as e:
        error_body = e.response.text[:500] if e.response else "No response body"
        return [types.TextContent(type="text", text=f"Kimi API error {e.response.status_code}: {error_body}")]
    except httpx.ConnectError:
        return [types.TextContent(type="text", text=f"Cannot connect to Kimi API at {BASE_URL}")]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error: {type(e).__name__}: {e}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
