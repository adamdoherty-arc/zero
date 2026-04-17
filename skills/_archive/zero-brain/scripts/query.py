#!/usr/bin/env python3
"""
Zero Brain - Routes user messages to the Zero backend LangGraph orchestration API.

Usage:
    python query.py "<message>" "<channel>" "<sender_id>"

Examples:
    python query.py "What sprints are active?" "whatsapp" "19044014854"
    python query.py "Show my calendar" "discord" "427818579812155402"
    python query.py "Any urgent emails?" "slack" "U12345"
"""

import os
import sys
import json

# Use urllib to avoid requiring requests package (OpenClaw containers may not have it)
import urllib.request
import urllib.error

BACKEND_URL = os.getenv("ZERO_BACKEND_URL", "http://zero-api:18792")
BACKEND_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", os.getenv("ZERO_GATEWAY_TOKEN", ""))
TIMEOUT = 60  # seconds - LangGraph can take 30-60s for complex queries


def build_thread_id(channel: str, sender_id: str) -> str:
    """Build a channel-specific thread ID for conversation state isolation."""
    clean_sender = sender_id.replace("+", "").strip()
    return f"{channel}-{clean_sender}" if clean_sender else f"{channel}-default"


def query_backend(message: str, thread_id: str) -> dict:
    """Send a message to the Zero backend LangGraph orchestration API."""
    url = f"{BACKEND_URL}/api/orchestrator/graph/invoke"

    payload = json.dumps({
        "message": message,
        "thread_id": thread_id,
    }).encode("utf-8")

    headers = {
        "Authorization": f"Bearer {BACKEND_TOKEN}",
        "Content-Type": "application/json",
    }

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {
                "success": True,
                "result": data.get("result", ""),
                "route": data.get("route", "general"),
                "thread_id": data.get("thread_id", thread_id),
            }
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return {
            "success": False,
            "error": f"HTTP {e.code}: {body[:200]}",
        }
    except urllib.error.URLError as e:
        return {
            "success": False,
            "error": f"Connection failed: {e.reason}",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def main():
    if len(sys.argv) < 2:
        print("Usage: query.py <message> [channel] [sender_id]")
        sys.exit(1)

    message = sys.argv[1]
    channel = sys.argv[2] if len(sys.argv) > 2 else "cli"
    sender_id = sys.argv[3] if len(sys.argv) > 3 else "default"

    thread_id = build_thread_id(channel, sender_id)
    result = query_backend(message, thread_id)

    if result["success"]:
        # Print just the natural language result for the chat response
        print(result["result"])
    else:
        # Backend unavailable - print error for OpenClaw to handle/fallback
        print(f"[Zero Backend unavailable: {result['error']}]")
        sys.exit(1)


if __name__ == "__main__":
    main()
