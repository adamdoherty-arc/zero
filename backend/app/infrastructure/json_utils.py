"""
Shared utilities for JSON extraction from LLM outputs, prompt sanitization, and retry helpers.
"""

import json
import re
from typing import Any, Optional

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Shared retry decorator for LLM calls — 3 attempts, exponential backoff 2-10s
llm_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((Exception,)),
    reraise=True,
)


def extract_json_from_text(text: str) -> Optional[Any]:
    """Extract the first valid JSON object from LLM text output.

    Handles nested structures (arrays, nested objects) by trying
    from the first '{' to the last '}', then progressively shorter substrings.
    """
    if not text:
        return None

    start = text.find("{")
    if start < 0:
        return None
    end = text.rfind("}")
    if end <= start:
        return None

    # Try the full outer braces first
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        pass

    # Try progressively shorter substrings from the end
    for e in range(end - 1, start, -1):
        if text[e] == "}":
            try:
                return json.loads(text[start : e + 1])
            except json.JSONDecodeError:
                continue

    return None


def sanitize_for_prompt(text: str, max_length: int = 500) -> str:
    """Strip prompt injection patterns from user-provided text before inserting into LLM prompts."""
    if not text:
        return ""
    patterns = [
        r"(?i)(ignore|forget)\s+(previous|all|above|prior)\s+(instructions?|prompts?|context)",
        r"(?i)you\s+are\s+now\s+a",
        r"(?i)new\s+system\s+prompt",
        r"(?i)\bsystem:\s",
        r"(?i)\bassistant:\s",
        r"(?i)\bhuman:\s",
    ]
    for p in patterns:
        text = re.sub(p, "[removed]", text)
    return text[:max_length]
