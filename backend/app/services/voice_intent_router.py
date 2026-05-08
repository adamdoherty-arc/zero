"""
Voice intent router for the email triage state machine.

Two-stage classifier:
  1. Keyword fast-path — exact / near-exact phrase match. ~0ms.
  2. LLM fallback — only when the user's words don't match a keyword cleanly.

The fast path covers the common case ("read", "ignore", "delete", "respond",
"send", "cancel", "yes", "no", "stop", "skip"). The LLM path catches paraphrases
("trash that one", "go ahead", "let's hear it") and emits the same intent enum.

This router is stateless. The session service owns "which intents are valid right
now"; the router just classifies free-form speech into a canonical intent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import structlog

logger = structlog.get_logger(__name__)


Intent = Literal[
    "read",
    "ignore",
    "delete",
    "respond",
    "send",
    "cancel",
    "skip",
    "stop",
    "unknown",
]


@dataclass
class IntentResult:
    intent: Intent
    confidence: float
    source: Literal["keyword", "llm", "default"]
    raw_text: str


# ------------------------------------------------------------------
# Keyword fast path
# ------------------------------------------------------------------

# Each intent has a list of trigger phrases. Order matters within a list — first
# match wins. Keep entries lowercase, no punctuation. We strip the input the
# same way before matching.
_KEYWORD_MAP: dict[Intent, list[str]] = {
    "read": [
        "read it", "read", "yes read", "go ahead", "yeah", "yes", "yep",
        "sure", "okay", "ok", "please", "let's hear it", "tell me",
    ],
    "ignore": [
        "ignore", "skip it", "skip", "not now", "later", "no thanks",
        "pass", "move on",
    ],
    "delete": [
        "delete", "trash", "trash it", "remove", "throw it out", "bin it",
        "delete it",
    ],
    "respond": [
        "respond", "reply", "respond to it", "reply to it", "write back",
        "answer", "draft a reply",
    ],
    "send": [
        "send", "send it", "ship it", "yes send", "looks good",
        "go", "fire it off",
    ],
    "cancel": [
        "cancel", "no", "nope", "don't send", "do not send", "abort",
        "scrap it", "wait",
    ],
    "skip": ["next", "next email", "skip this one", "move along"],
    "stop": ["stop", "shut up", "quiet", "be quiet", "enough"],
}


def _normalize(text: str) -> str:
    return " ".join(text.lower().strip().rstrip(".!?,").split())


def _keyword_classify(text: str, allowed: list[Intent]) -> Optional[IntentResult]:
    """Return an intent only if the normalized text matches a keyword for an allowed intent."""
    norm = _normalize(text)
    if not norm:
        return None
    # Exact match first (highest confidence)
    for intent in allowed:
        for phrase in _KEYWORD_MAP.get(intent, []):
            if norm == phrase:
                return IntentResult(
                    intent=intent, confidence=0.95, source="keyword", raw_text=text
                )
    # Substring match (whole-word boundary check)
    tokens = norm.split()
    token_set = set(tokens)
    for intent in allowed:
        for phrase in _KEYWORD_MAP.get(intent, []):
            phrase_tokens = phrase.split()
            if len(phrase_tokens) == 1:
                if phrase_tokens[0] in token_set:
                    return IntentResult(
                        intent=intent, confidence=0.85, source="keyword", raw_text=text
                    )
            elif phrase in norm:
                return IntentResult(
                    intent=intent, confidence=0.8, source="keyword", raw_text=text
                )
    return None


# ------------------------------------------------------------------
# LLM fallback
# ------------------------------------------------------------------

_LLM_PROMPT = """You are an intent classifier for a voice email assistant.
The user just said something while triaging emails. Classify their intent.

Allowed intents (pick exactly one):
{allowed}

Reply with ONLY the intent word, nothing else.
If none of the allowed intents fit, reply: unknown
"""


async def _llm_classify(text: str, allowed: list[Intent]) -> IntentResult:
    """Classify via LLM. Falls back to 'unknown' on any error."""
    try:
        from app.infrastructure.unified_llm_client import get_unified_llm_client

        client = get_unified_llm_client()
        prompt = (
            _LLM_PROMPT.format(allowed="\n".join(f"- {a}" for a in allowed))
            + f"\n\nUser said: {text!r}\nIntent:"
        )
        raw = await client.chat(
            prompt=prompt,
            task_type="classify",
            temperature=0.1,
            max_tokens=10,
        )
        if isinstance(raw, dict):
            raw = raw.get("content") or raw.get("response") or ""
        candidate = _normalize(str(raw)).split()
        if candidate:
            cand = candidate[0].rstrip(".,!?")
            if cand in allowed:
                return IntentResult(
                    intent=cand,  # type: ignore[arg-type]
                    confidence=0.7,
                    source="llm",
                    raw_text=text,
                )
        return IntentResult(intent="unknown", confidence=0.0, source="llm", raw_text=text)
    except Exception as e:
        logger.debug("voice_intent_llm_failed", error=str(e))
        return IntentResult(intent="unknown", confidence=0.0, source="default", raw_text=text)


async def classify_intent(
    text: str,
    *,
    allowed: list[Intent],
    use_llm_fallback: bool = True,
) -> IntentResult:
    """Classify free-form user speech into one of the allowed intents.

    Args:
        text: Transcribed user speech.
        allowed: Subset of Intent values that the current state accepts.
        use_llm_fallback: If True, ambiguous input goes to LLM. Set False in tight
            loops where keyword-only is enough.
    """
    keyword = _keyword_classify(text, allowed)
    if keyword is not None:
        return keyword
    if use_llm_fallback:
        return await _llm_classify(text, allowed)
    return IntentResult(intent="unknown", confidence=0.0, source="default", raw_text=text)
