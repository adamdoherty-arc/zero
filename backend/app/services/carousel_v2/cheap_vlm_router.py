"""Tiered cheap-VLM dispatcher for Stage-8 image verification.

Tier order (chosen by the user 2026-04-28 — see plan file):

    Tier 0: Gemini 2.5 Flash            (paid, $0.075/M tokens, gated by budget)
    Tier 1: OpenRouter free vision pool (free, rotates models × keys, always allowed)

Kimi was dropped from the VLM path on 2026-04-28 — Moonshot doesn't expose a
public vision SKU yet. The Kimi text path remains unchanged for designer /
skeptic / judges.

Each tier is failure-soft: 429 → cooldown + try next slot in same tier;
5xx → exponential backoff inside the slot then escalate; auth errors →
black-list key.

Budget enforcement (``vlm_budget``):

  - Daily spend cap (``ZERO_VLM_DAILY_BUDGET_USD``, default $1) — when the
    next paid call's *estimated* cost would exceed the daily total, Tier 0
    is skipped for that call.
  - Per-carousel cap (``ZERO_VLM_PER_CAROUSEL_CAP_USD``, default $0.10) —
    same gate but scoped to the current ``generation_id``.
  - Free pool is exempt (cost = 0).

When every tier is gated/exhausted, the router returns a failure-soft
envelope and Stage 9 ranks the image without a VLM signal.

Public entrypoint::

    result = await verify_image(
        image_url_or_bytes="https://...",
        character="Homelander",
        franchise="the_boys",
        generation_id="gen-abc",   # for per-carousel cap tracking
    )
    # → {"likeness": 0.92, "watermark": False, ...,
    #    "_model": "openrouter/google/gemma-3-27b-it:free",
    #    "_tier":  "openrouter_free",
    #    "_cost_usd": 0.0,
    #    "_available": True}
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

import structlog

from app.infrastructure.config import get_settings
from app.services.carousel_v2.openrouter_free_pool import (
    get_openrouter_free_pool,
)
from app.services.carousel_v2.vlm_budget import get_vlm_budget

logger = structlog.get_logger(__name__)


VLM_PROMPT_TEMPLATE = (
    "You verify whether the image shows {character}{franchise_clause}.\n"
    "Return JSON only with these keys:\n"
    "  character (string), actor (string|null), franchise (string|null),\n"
    "  likeness (float in [0,1]), is_promotional_still (bool),\n"
    "  watermark (bool), text_overlay (bool),\n"
    "  vertical_safe_crop_box ({{top,left,width,height}} as fractions of image, or null).\n"
    "No prose, no code fences."
)


def _build_prompt(character: str, franchise: Optional[str]) -> str:
    return VLM_PROMPT_TEMPLATE.format(
        character=character,
        franchise_clause=f" from {franchise}" if franchise else "",
    )


def _strip_fences(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _parse_json(text: str) -> Optional[dict]:
    text = _strip_fences(text)
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except Exception:  # noqa: BLE001
        # Try a regex extraction for stubborn responses.
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                parsed = json.loads(m.group())
                return parsed if isinstance(parsed, dict) else None
            except Exception:  # noqa: BLE001
                return None
    return None


def _normalise_likeness(parsed: dict) -> dict:
    """Coerce parsed JSON into the canonical ImageScore-ready shape."""
    out: dict[str, Any] = {
        "character": parsed.get("character"),
        "actor": parsed.get("actor"),
        "franchise": parsed.get("franchise"),
        "likeness": None,
        "is_promotional_still": bool(parsed.get("is_promotional_still"))
            if parsed.get("is_promotional_still") is not None else None,
        "watermark": bool(parsed.get("watermark", False)),
        "text_overlay": bool(parsed.get("text_overlay", False)),
        "vertical_safe_crop_box": parsed.get("vertical_safe_crop_box"),
    }
    raw_lik = parsed.get("likeness")
    if isinstance(raw_lik, (int, float)):
        out["likeness"] = max(0.0, min(1.0, float(raw_lik)))
    return out


# ---------------------------------------------------------------------------
# Tier dispatchers
# ---------------------------------------------------------------------------

# Approximate token cost per VLM call. The prompt is ~120 tokens; image
# tokenisation varies wildly, but ~800 tokens is a fair midpoint for a
# 1080p image at standard tile resolution.
_AVG_INPUT_TOKENS = 920
_AVG_OUTPUT_TOKENS = 200


async def _try_gemini(
    image_url: str,
    *,
    character: str,
    franchise: Optional[str],
    generation_id: Optional[str],
    timeout: float,
) -> Optional[dict]:
    """Tier 0 — paid Gemini Flash, gated by daily + per-carousel budget caps.

    The estimated cost is checked BEFORE the call so we never spend money we
    weren't going to spend. After a successful call the actual cost is
    recorded against both counters.
    """
    settings = get_settings()
    if not settings.gemini_api_key:
        return None
    try:
        from app.infrastructure.llm_providers import get_provider
        provider = get_provider("gemini")
        if provider is None:
            return None
    except Exception:  # noqa: BLE001
        return None

    # ``gemini-2.5-flash-lite`` is the current cheapest stable vision-capable
    # SKU on the v1beta endpoint ($0.025/M input, $0.10/M output). Avoids the
    # ``gemini-flash-latest`` rolling alias which resolves to a thinking
    # model that consumes ``max_output_tokens`` on internal reasoning and
    # truncates the visible JSON response.
    # Override with ZERO_GEMINI_VISION_MODEL once 3.1 GA hits v1beta.
    model = os.getenv("ZERO_GEMINI_VISION_MODEL", "gemini-2.5-flash-lite")
    estimated = provider.estimate_cost(_AVG_INPUT_TOKENS, _AVG_OUTPUT_TOKENS, model)

    budget = await get_vlm_budget()
    if not await budget.can_spend(generation_id=generation_id, estimated_cost_usd=estimated):
        # Budget gate fired — skip Tier 0 cleanly so the free pool catches.
        return None

    prompt = _build_prompt(character, franchise)
    messages = [{"role": "user", "content": prompt}]
    try:
        text = await provider.chat(
            messages=messages,
            model=model,
            temperature=0.0,
            max_tokens=1024,
            json_mode=True,
            image_urls=[image_url],
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("vlm_gemini_failed", error=str(exc))
        return None

    parsed = _parse_json(text)
    if parsed is None:
        logger.debug("vlm_gemini_parse_failed", raw=str(text)[:120])
        return None

    # Record actual cost (using the per-call estimate as the actual; provider
    # doesn't surface real token counts post-call).
    await budget.record(generation_id=generation_id, cost_usd=estimated)

    out = _normalise_likeness(parsed)
    out["_model"] = f"gemini/{model}"
    out["_tier"] = "gemini_paid"
    out["_cost_usd"] = estimated
    out["_available"] = True
    return out


async def _try_openrouter_free(
    image_url: str,
    *,
    character: str,
    franchise: Optional[str],
    generation_id: Optional[str] = None,
    timeout: float,
) -> Optional[dict]:
    pool = await get_openrouter_free_pool()

    try:
        from app.infrastructure.llm_providers import get_provider
        from app.infrastructure.llm_providers.openrouter_provider import RateLimitError
        provider = get_provider("openrouter")
        if provider is None:
            return None
    except Exception:  # noqa: BLE001
        return None

    prompt = _build_prompt(character, franchise)
    messages = [{"role": "user", "content": prompt}]

    # ``select_next`` triggers the lazy model-list fetch on first call, so
    # ``slot_count`` only becomes non-zero after we've tried at least once.
    # Use a hard upper bound (32) on rotation attempts to bound latency.
    max_attempts = 32
    for _ in range(max_attempts):
        slot = await pool.select_next()
        if slot is None:
            return None
        key, model = slot
        try:
            text = await provider.chat(
                messages=messages,
                model=model,
                temperature=0.0,
                max_tokens=512,
                json_mode=True,
                image_urls=[image_url],
                api_key_override=key,
            )
        except RateLimitError as exc:
            await pool.mark_429(slot, retry_after=exc.retry_after)
            continue
        except Exception as exc:  # noqa: BLE001
            err = str(exc).lower()
            if "401" in err or "403" in err or "unauthorized" in err:
                await pool.mark_auth_failure(slot)
            else:
                logger.debug("vlm_openrouter_failed", model=model, error=str(exc))
            continue

        parsed = _parse_json(text)
        if parsed is None:
            logger.debug("vlm_openrouter_parse_failed", model=model, raw=str(text)[:120])
            await pool.mark_success(slot)  # successful call, just bad output — quota still consumed
            continue

        await pool.mark_success(slot, tokens_used=_AVG_INPUT_TOKENS + _AVG_OUTPUT_TOKENS)
        out = _normalise_likeness(parsed)
        out["_model"] = f"openrouter/{model}"
        out["_tier"] = "openrouter_free"
        out["_cost_usd"] = 0.0
        out["_available"] = True
        return out

    return None


# NOTE: ``_try_gemini_paid`` was the legacy Tier-2 path in the original
# cheap-VLM router. It's been folded into ``_try_gemini`` (Tier 0) above
# which adds budget-cap gating before the call. Kept this comment as a
# breadcrumb; future code should call ``_try_gemini``.


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

async def verify_image(
    image_url: str,
    *,
    character: str,
    franchise: Optional[str] = None,
    generation_id: Optional[str] = None,
    timeout: float = 30.0,
) -> dict:
    """Walk Tier 0 (Gemini paid, budget-gated) → Tier 1 (OpenRouter free pool)
    until one returns a parseable verdict.

    Always returns a dict. Failure-soft: if every tier fails or is gated,
    returns ``{"_available": False, "_tier": "exhausted", "error": "..."}``.
    Stage 9 of the image scorer treats missing VLM signal as "no info" and
    ranks on the cheap-CV signals only.

    ``generation_id`` is the carousel V2 generation key — when set, the
    per-carousel budget cap also applies, so one runaway generation can't
    eat the whole daily ceiling.
    """
    for fn, tier_name in (
        (_try_gemini, "gemini_paid"),
        (_try_openrouter_free, "openrouter_free"),
    ):
        try:
            result = await fn(
                image_url,
                character=character,
                franchise=franchise,
                generation_id=generation_id,
                timeout=timeout,
            )
        except Exception as exc:  # noqa: BLE001 — never let routing crash Stage 8
            logger.warning("vlm_tier_unhandled_error", tier=tier_name, error=str(exc))
            continue
        if result is not None:
            logger.info(
                "vlm_verify_done",
                character=character,
                tier=result.get("_tier"),
                model=result.get("_model"),
                likeness=result.get("likeness"),
                cost_usd=result.get("_cost_usd"),
            )
            return result

    logger.warning("vlm_verify_all_tiers_exhausted", character=character)
    return {
        "_available": False,
        "_tier": "exhausted",
        "_model": None,
        "_cost_usd": 0.0,
        "error": "all_tiers_exhausted",
        "likeness": None,
        "watermark": False,
        "text_overlay": False,
        "is_promotional_still": None,
        "vertical_safe_crop_box": None,
        "character": None,
        "actor": None,
        "franchise": None,
    }
