"""
Hint-based routing aliases for the LLM router.

This module layers a coarse `hint:*` taxonomy on top of the existing
``task_assignments`` system in ``llm_router.py``. Hints are the surface that
callers — especially small helpers, tool-output compactors, reflection loops,
and reaction generators — use when they don't know (or care) which exact task
this is, only the *shape* of the call:

  • hint:reaction      → short snappy ack (≤1 sentence)
  • hint:classify      → label / intent / yes-no
  • hint:format        → reformat / pretty-print
  • hint:sentiment     → tone classification
  • hint:summarize     → 1-paragraph compaction
  • hint:medium        → ordinary chat-shaped Q&A
  • hint:tool_lite     → small tool-result reformatting
  • hint:reflection    → background self-reflection over recent context

  • hint:reasoning     → multi-step reasoning (cloud-preferred)
  • hint:agentic       → tool-use loops (cloud-preferred)
  • hint:coding        → code understanding / generation (cloud-preferred)
  • hint:vision        → image / VLM (vision provider preferred)

Presets ("everything local", "memory + reflection", "embeddings only") swing
the resolved provider for the local-eligible group. Heavy hints stay cloud.

The router stays the source of truth for actual ``ModelAssignment`` rows; this
module only maps hint strings to existing ``task_type`` keys plus an optional
local-vs-cloud override. That keeps budget tracking, fallback chains, and
per-task params intact.
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Dict, Optional

import structlog

logger = structlog.get_logger(__name__)


HINT_PREFIX = "hint:"


class HintPreset(str, Enum):
    """User-selectable presets that bias hint resolution toward local providers."""

    DEFAULT = "default"  # local-eligible hints go to their normal local tier
    EMBEDDINGS_ONLY = "embeddings_only"  # only embeddings local; everything else cloud
    MEMORY_REFLECTION = "memory_reflection"  # memory / reflection / summarize local; rest default
    EVERYTHING_LOCAL = "everything_local"  # force all hints to vllm/ollama where viable


# Hints that are safe / cheap to run on the local provider (vLLM qwen3-chat or
# Ollama). Cloud hints (reasoning/agentic/coding/vision) are excluded and
# always resolve via their cloud task_type.
_LOCAL_ELIGIBLE = {
    "reaction",
    "classify",
    "format",
    "sentiment",
    "summarize",
    "medium",
    "tool_lite",
    "reflection",
}


# Map each hint to an existing ``task_type`` in ``LlmRouterConfig``. The router
# already has good defaults for these, so we route through them and get the
# fallback chain, temperature, num_predict for free.
HINT_TO_TASK_TYPE: Dict[str, str] = {
    "reaction": "chat",
    "classify": "classification",
    "format": "structured_output",
    "sentiment": "classification",
    "summarize": "summarization",
    "medium": "chat",
    "tool_lite": "extraction",
    "reflection": "analysis",
    "reasoning": "planning",
    "agentic": "planning",
    "coding": "coding",
    "vision": "analysis",
}


# Forced model spec per preset+hint when the preset wants to override the task
# assignment. Empty string means "use the task_type default".
_PRESET_OVERRIDES: Dict[HintPreset, Dict[str, str]] = {
    HintPreset.DEFAULT: {},
    HintPreset.EMBEDDINGS_ONLY: {
        # Force every local-eligible hint to cloud — only embeddings stay local.
        "reaction": "minimax/MiniMax-M2.7",
        "classify": "minimax/MiniMax-M2.7",
        "format": "minimax/MiniMax-M2.7",
        "sentiment": "minimax/MiniMax-M2.7",
        "summarize": "kimi/kimi-k2.6",
        "medium": "kimi/kimi-k2.6",
        "tool_lite": "minimax/MiniMax-M2.7",
        "reflection": "kimi/kimi-k2.6",
    },
    HintPreset.MEMORY_REFLECTION: {
        # Memory + reflection workloads run local; others default.
        "summarize": "vllm/qwen3-chat",
        "reflection": "vllm/qwen3-chat",
        "tool_lite": "vllm/qwen3-chat",
    },
    HintPreset.EVERYTHING_LOCAL: {
        "reaction": "vllm/qwen3-chat",
        "classify": "vllm/qwen3-chat",
        "format": "vllm/qwen3-chat",
        "sentiment": "vllm/qwen3-chat",
        "summarize": "vllm/qwen3-chat",
        "medium": "vllm/qwen3-chat",
        "tool_lite": "vllm/qwen3-chat",
        "reflection": "vllm/qwen3-chat",
        # Cloud hints stay cloud even on "everything local" — pushing reasoning
        # to a 7B is regression for the user.
    },
}


def parse_hint(value: Optional[str]) -> Optional[str]:
    """Extract the bare hint name from ``hint:foo`` or ``foo``. Returns None for empty."""
    if not value:
        return None
    if value.startswith(HINT_PREFIX):
        return value[len(HINT_PREFIX):].strip().lower() or None
    return value.strip().lower() or None


def is_local_eligible(hint: str) -> bool:
    return parse_hint(hint) in _LOCAL_ELIGIBLE


def get_current_preset() -> HintPreset:
    """Read the active preset from env. Defaults to DEFAULT."""
    raw = os.getenv("ZERO_HINT_PRESET", "").strip().lower()
    try:
        return HintPreset(raw) if raw else HintPreset.DEFAULT
    except ValueError:
        logger.warning("hint_preset_invalid", value=raw)
        return HintPreset.DEFAULT


def resolve_hint_task_type(hint: str) -> str:
    """Map a hint string to the existing task_type key the router knows about.

    Unknown hints fall through to ``chat`` so callers never crash.
    """
    bare = parse_hint(hint)
    if not bare:
        return "chat"
    return HINT_TO_TASK_TYPE.get(bare, "chat")


def resolve_hint_override(hint: str, preset: Optional[HintPreset] = None) -> Optional[str]:
    """Return a ``provider/model`` string to force, or None to let the router
    decide via the normal task_assignments path.
    """
    bare = parse_hint(hint)
    if not bare:
        return None
    active = preset if preset is not None else get_current_preset()
    return _PRESET_OVERRIDES.get(active, {}).get(bare) or None


def all_hints() -> list[str]:
    return sorted(HINT_TO_TASK_TYPE.keys())


def all_presets() -> list[str]:
    return [p.value for p in HintPreset]
