"""
Vision-LLM promo extractor for meal-service homepages.

Visits each tracked service's homepage, takes a full-page screenshot,
and asks a vision-capable LLM (Gemini 2.5 Flash Vision via the shared
router) to extract promo codes / welcome offers visible in hero banners,
popup modals, and referral-code blocks that pure text scraping can't see.

Gated behind ``MEAL_VISION_ENABLED=1`` — stays completely dormant until
opted in. Playwright is an optional dep; the service degrades to a no-op
import error rather than crashing the backend.
"""

from __future__ import annotations

import asyncio
import base64
import json as _json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import structlog
from sqlalchemy import select

from app.db.models import MealPromoCodeModel, MealServiceModel
from app.infrastructure.database import get_session
from app.models.meal import PromoDiscountType, PromoSource
from app.services.meal_promo_hunter_service import MealPromoHunterService

try:
    from playwright.async_api import async_playwright  # type: ignore
except Exception:  # pragma: no cover
    async_playwright = None  # type: ignore

try:
    from app.infrastructure.unified_llm_client import get_unified_llm_client
except Exception:  # pragma: no cover
    get_unified_llm_client = None  # type: ignore


logger = structlog.get_logger(__name__)


def _vision_enabled() -> bool:
    return os.getenv("MEAL_VISION_ENABLED", "").lower() in ("1", "true", "yes")


class MealVisionExtractorService:
    """Weekly sweep: screenshot each merchant's homepage and have the LLM
    extract visible promo codes."""

    async def sweep(self) -> dict:
        if not _vision_enabled():
            logger.info("meal_vision_sweep_disabled", reason="MEAL_VISION_ENABLED not set")
            return {"status": "disabled", "processed": 0, "extracted": 0}
        if async_playwright is None:
            logger.warning("meal_vision_sweep_skipped", reason="playwright not installed")
            return {"status": "no_playwright", "processed": 0, "extracted": 0}
        if get_unified_llm_client is None:
            return {"status": "no_llm", "processed": 0, "extracted": 0}

        async with get_session() as session:
            services = (
                await session.execute(
                    select(MealServiceModel).where(MealServiceModel.status == "tracked")
                )
            ).scalars().all()

        processed = 0
        extracted = 0
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                for svc in services:
                    try:
                        items = await self._process_service(browser, svc)
                    except Exception as e:
                        logger.debug("vision_service_failed", service=svc.slug, error=str(e))
                        continue
                    processed += 1
                    for code_info in items:
                        was_new = await self._persist(svc.id, svc.slug, code_info)
                        if was_new:
                            extracted += 1
            finally:
                await browser.close()

        logger.info(
            "meal_vision_sweep_complete",
            processed=processed,
            extracted=extracted,
        )
        return {"status": "ok", "processed": processed, "extracted": extracted}

    async def _process_service(self, browser, svc: MealServiceModel) -> list[dict]:
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
        )
        page = await context.new_page()
        try:
            await page.goto(svc.website_url, wait_until="domcontentloaded", timeout=25_000)
            # Small wait to let hero banners animate into place
            await page.wait_for_timeout(2500)
            screenshot_bytes = await page.screenshot(full_page=False, type="png")
        finally:
            await context.close()

        b64 = base64.b64encode(screenshot_bytes).decode("ascii")
        prompt = f"""You are looking at a screenshot of the homepage of {svc.name} (a meal-delivery service).

Extract every visible promo code, welcome offer, referral bonus, or banner
discount that applies to {svc.name}. DO NOT include:
 - offers for other merchants
 - generic "sign up for our newsletter" prompts without a code/discount
 - shipping-cost disclaimers

Return JSON only: {{"promos": [{{"code": "<literal code or null>", "discount_type": "percent|dollar|free_shipping|bogo", "value": <number>, "description": "<under 120 chars>", "is_referral": <true/false>}}]}}
"""
        try:
            client = get_unified_llm_client()
            raw = await client.chat(
                prompt=prompt,
                task_type="meal_vision_extract",
                temperature=0.0,
                max_tokens=1200,
                json_mode=True,
                images=[{"mime_type": "image/png", "data": b64}],  # handled by provider if supported
            )
        except TypeError:
            # Provider doesn't support images kwarg — fall back to pure-text prompt
            return []
        except Exception as e:
            logger.debug("vision_llm_failed", service=svc.slug, error=str(e))
            return []

        data: Any
        try:
            data = _json.loads(raw)
        except Exception:
            stripped = raw.strip().strip("`")
            if stripped.startswith("json"):
                stripped = stripped[4:].strip()
            try:
                data = _json.loads(stripped)
            except Exception:
                return []

        promos = data.get("promos") if isinstance(data, dict) else data
        if not isinstance(promos, list):
            return []

        out: list[dict] = []
        for p in promos:
            if not isinstance(p, dict):
                continue
            d_type = p.get("discount_type") or ""
            if d_type not in {"percent", "dollar", "free_shipping", "bogo"}:
                continue
            try:
                value = float(p.get("value") or 0)
            except (TypeError, ValueError):
                continue
            out.append({
                "code": (p.get("code") or "").strip().upper() or None,
                "discount_type": d_type,
                "value": value,
                "description": (p.get("description") or "")[:200],
                "is_referral": bool(p.get("is_referral")),
            })
        return out

    async def _persist(self, service_id: str, service_slug: str, code_info: dict) -> bool:
        """Upsert via the shared hunter upsert logic."""
        hunter = MealPromoHunterService()
        return await hunter._upsert_promo(
            service_id=service_id,
            service_slug=service_slug,
            source=PromoSource.VISION.value,
            source_url=f"vision://{service_slug}",
            code=code_info.get("code"),
            discount_type=code_info.get("discount_type", "percent"),
            discount_value=code_info.get("value", 0.0),
            description=code_info.get("description"),
            is_referral=code_info.get("is_referral", False),
            new_customer_only=code_info.get("is_referral", False),
        )


_singleton: Optional[MealVisionExtractorService] = None


def get_meal_vision_extractor() -> MealVisionExtractorService:
    global _singleton
    if _singleton is None:
        _singleton = MealVisionExtractorService()
    return _singleton
