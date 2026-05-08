"""
Email-signup intercept for meal services.

Two responsibilities:

1. **Signup half** (gated behind ``MEAL_SIGNUP_ENABLED=1`` + working
   Playwright): for each tracked meal service, sign up its newsletter
   using a catch-all alias derived from ``MEAL_SIGNUP_ALIAS_TEMPLATE``
   (e.g. ``meals+{slug}@yourcatchall.com``). Runs at most once per
   service every ``signup_cooldown_days`` (default 90) using
   ``MealServiceModel.metadata_.last_signup_at`` as the throttle.

2. **Parse half** (always-on): scans the Gmail cache for welcome
   emails from meal-service senders that contain a visible promo code
   ("use SAVE30 at checkout"). LLM-extracts structured codes and
   persists them as ``PromoSource.SIGNUP_INTERCEPT`` with
   ``new_customer_only=True``. This half works even if the signup
   automation never runs — any time the user signs up manually on
   their own, the welcome email gets captured.

The welcome-email parser runs as part of the regular shipment scan
scheduler job, piggy-backing on the existing Gmail cache.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import and_, select

from app.db.models import EmailCacheModel, MealPromoCodeModel, MealServiceModel
from app.infrastructure.database import get_session
from app.models.meal import PromoSource
from app.services.meal_promo_hunter_service import MealPromoHunterService

try:
    from playwright.async_api import async_playwright  # type: ignore
except Exception:  # pragma: no cover
    async_playwright = None  # type: ignore


logger = structlog.get_logger(__name__)

WELCOME_SUBJECT_HINTS = (
    "welcome", "here's your", "your code", "your discount", "first order",
    "thanks for joining", "get started", "%", "off"
)


def _signup_enabled() -> bool:
    return os.getenv("MEAL_SIGNUP_ENABLED", "").lower() in ("1", "true", "yes")


def _alias_for(slug: str) -> Optional[str]:
    template = os.getenv("MEAL_SIGNUP_ALIAS_TEMPLATE", "").strip()
    if not template or "{slug}" not in template:
        return None
    return template.format(slug=slug)


class MealSignupSweeperService:
    def __init__(self):
        self._cooldown = timedelta(days=int(os.getenv("MEAL_SIGNUP_COOLDOWN_DAYS", "90")))

    # ------------------------------------------------------------------
    # Half 1 — Playwright signup (env-gated)
    # ------------------------------------------------------------------

    async def sweep_signups(self) -> dict:
        if not _signup_enabled():
            return {"status": "disabled", "signed_up": 0}
        if async_playwright is None:
            return {"status": "no_playwright", "signed_up": 0}

        now = datetime.utcnow()
        async with get_session() as session:
            services = (
                await session.execute(
                    select(MealServiceModel).where(MealServiceModel.status == "tracked")
                )
            ).scalars().all()

        signed_up = 0
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                for svc in services:
                    meta = dict(svc.metadata_ or {})
                    last_at = meta.get("last_signup_at")
                    try:
                        if last_at and datetime.fromisoformat(str(last_at)) > now - self._cooldown:
                            continue
                    except Exception:
                        pass
                    alias = _alias_for(svc.slug)
                    if not alias:
                        continue
                    ok = await self._try_signup(browser, svc.website_url, alias)
                    if ok:
                        signed_up += 1
                        async with get_session() as s2:
                            row = await s2.get(MealServiceModel, svc.id)
                            if row:
                                m = dict(row.metadata_ or {})
                                m["last_signup_at"] = now.isoformat()
                                row.metadata_ = m
            finally:
                await browser.close()

        logger.info("meal_signup_sweep_complete", signed_up=signed_up)
        return {"status": "ok", "signed_up": signed_up}

    async def _try_signup(self, browser, homepage: str, alias: str) -> bool:
        """Best-effort: visit homepage, find a footer newsletter input, type
        the alias, submit. Returns True on successful form submission."""
        context = await browser.new_context()
        page = await context.new_page()
        try:
            await page.goto(homepage, wait_until="domcontentloaded", timeout=25_000)
            await page.wait_for_timeout(1500)
            # Try the most common selectors in order of specificity
            selectors = [
                'input[type="email"][name*="email" i]',
                'input[type="email"]',
                'input[placeholder*="email" i]',
            ]
            for sel in selectors:
                locator = page.locator(sel).first
                try:
                    if await locator.count() == 0:
                        continue
                    await locator.scroll_into_view_if_needed(timeout=3000)
                    await locator.fill(alias, timeout=3000)
                    # Try submitting: press Enter, then look for a submit button
                    await locator.press("Enter", timeout=2000)
                    await page.wait_for_timeout(1500)
                    return True
                except Exception:
                    continue
            return False
        except Exception as e:
            logger.debug("signup_attempt_failed", homepage=homepage, error=str(e))
            return False
        finally:
            await context.close()

    # ------------------------------------------------------------------
    # Half 2 — Welcome-email parser (always on)
    # ------------------------------------------------------------------

    async def parse_welcome_emails(self, *, lookback_days: int = 30) -> dict:
        """Scan email_cache for meal-service welcome emails and extract codes."""
        since = datetime.utcnow() - timedelta(days=lookback_days)
        async with get_session() as session:
            services = (
                await session.execute(
                    select(MealServiceModel).where(MealServiceModel.status == "tracked")
                )
            ).scalars().all()

        domain_patterns: list[tuple[str, MealServiceModel]] = []
        for svc in services:
            for pat in (svc.email_sender_patterns or []):
                p = pat.strip().lstrip("@").lower()
                if p and "." in p:
                    domain_patterns.append((p, svc))

        if not domain_patterns:
            return {"status": "no_patterns", "processed": 0, "extracted": 0}

        async with get_session() as session:
            rows = (
                await session.execute(
                    select(EmailCacheModel).where(EmailCacheModel.received_at >= since)
                )
            ).scalars().all()

        processed = 0
        extracted = 0
        hunter = MealPromoHunterService()

        for email in rows:
            from_addr = email.from_address or {}
            if not isinstance(from_addr, dict):
                continue
            sender_email = (from_addr.get("email") or "").lower()
            if "@" not in sender_email:
                continue
            sender_domain = sender_email.split("@")[-1]
            matched_svc: Optional[MealServiceModel] = None
            for domain, svc in domain_patterns:
                if sender_domain == domain or sender_domain.endswith("." + domain):
                    matched_svc = svc
                    break
            if not matched_svc:
                continue

            subject = (email.subject or "").lower()
            body = (email.body_text or email.snippet or "")[:8000]
            if not body:
                continue
            if not any(h in subject or h in body.lower() for h in WELCOME_SUBJECT_HINTS):
                continue
            processed += 1

            try:
                items = await hunter._extract_codes_llm(
                    body, matched_svc.name, matched_svc.slug
                )
            except Exception as e:
                logger.debug("welcome_extract_failed", service=matched_svc.slug, error=str(e))
                continue
            for code_info in items:
                try:
                    was_new = await hunter._upsert_promo(
                        service_id=matched_svc.id,
                        service_slug=matched_svc.slug,
                        source=PromoSource.SIGNUP_INTERCEPT.value,
                        source_url=f"gmail://{email.id}",
                        code=code_info.get("code"),
                        discount_type=code_info.get("discount_type", "percent"),
                        discount_value=code_info.get("value", 0.0),
                        description=code_info.get("description"),
                        new_customer_only=True,
                    )
                    if was_new:
                        extracted += 1
                except Exception as e:
                    logger.debug(
                        "welcome_upsert_failed", service=matched_svc.slug, error=str(e)
                    )

        logger.info(
            "meal_signup_parse_complete",
            processed=processed,
            extracted=extracted,
        )
        return {"status": "ok", "processed": processed, "extracted": extracted}


_singleton: Optional[MealSignupSweeperService] = None


def get_meal_signup_sweeper() -> MealSignupSweeperService:
    global _singleton
    if _singleton is None:
        _singleton = MealSignupSweeperService()
    return _singleton
