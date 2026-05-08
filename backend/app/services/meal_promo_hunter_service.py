"""
Promo code hunter.

Strategy per tracked meal service:
  1. Scrape the aggregator pages (RetailMeNot, CouponFollow, Reddit search)
     via the tiered scraper (httpx → Jina → optional Firecrawl).
  2. Extract codes using regex + LLM as a structured fallback.
  3. Upsert into meal_promo_codes, bumping times_seen + last_seen.
  4. Also hunt Rakuten / TopCashback / BeFrugal cashback percentages and
     upsert into meal_rebate_portal_offers.

We don't hit any site's private API or logged-in pages. Everything is from
publicly-browsable aggregator pages that Honey/Coupert/Kudos themselves scrape.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

import structlog
from sqlalchemy import select

from app.db.models import (
    MealPromoCodeModel,
    MealRebatePortalOfferModel,
    MealServiceModel,
)
from app.infrastructure.database import get_session
from app.models.meal import (
    PromoSource,
    PromoDiscountType,
    RebatePortal,
)
from app.services.meal_scraper_service import get_meal_scraper

try:
    from app.infrastructure.unified_llm_client import get_unified_llm_client
except Exception:  # pragma: no cover
    get_unified_llm_client = None  # type: ignore

logger = structlog.get_logger(__name__)


# HTML aggregator sources extracted via the LLM. Each merchant-scoped page
# has light cross-linking so the LLM reliably attributes codes correctly.
def _aggregator_urls(slug: str, website_host: str, merchant_homepage: str) -> list[tuple[str, str]]:
    """Returns list of (source, url) for HTML pages sent through LLM extraction."""
    brand = slug.replace("-", "")
    return [
        (PromoSource.COUPONFOLLOW.value,
         f"https://couponfollow.com/site/{website_host}"),
        (PromoSource.COUPONFOLLOW.value,
         f"https://couponfollow.com/site/{brand}.com"),
        (PromoSource.WETHRIFT.value,
         f"https://www.wethrift.com/{slug}"),
        (PromoSource.WETHRIFT.value,
         f"https://www.wethrift.com/{brand}"),
        (PromoSource.KNOJI.value,
         f"https://{slug}.knoji.com/promo-codes/"),
        (PromoSource.KNOJI.value,
         f"https://{brand}.knoji.com/promo-codes/"),
        (PromoSource.SLICKDEALS.value,
         f"https://slickdeals.net/coupons/{slug}/"),
        (PromoSource.SLICKDEALS.value,
         f"https://slickdeals.net/coupons/{brand}/"),
        # Merchant's own site — banner text often mentions a welcome offer
        (PromoSource.DIRECT.value, merchant_homepage),
    ]


# JSON endpoints (Capital One Shopping, Reddit search) — skip LLM, parse
# directly.
def _json_api_urls(slug: str, website_host: str, merchant_name: str) -> list[tuple[str, str]]:
    """Returns list of (source, url) for structured JSON sources."""
    import urllib.parse as _u
    brand = slug.replace("-", "")
    q = _u.quote_plus(f'"{merchant_name}" code')
    q_promo = _u.quote_plus(f"{merchant_name} promo")
    return [
        # Capital One Shopping — undocumented but public JSON endpoint
        (PromoSource.CAPITAL_ONE_SHOPPING.value,
         f"https://capitaloneshopping.com/api/v4/merchant/{slug}/offers"),
        (PromoSource.CAPITAL_ONE_SHOPPING.value,
         f"https://capitaloneshopping.com/api/v4/merchant/{brand}/offers"),
        # Reddit — public JSON search, limited to meal-kit-adjacent subs
        (PromoSource.REDDIT.value,
         f"https://www.reddit.com/r/MealKits/search.json?q={q}&restrict_sr=1&sort=new&limit=25"),
        (PromoSource.REDDIT.value,
         f"https://www.reddit.com/r/frugal/search.json?q={q_promo}&restrict_sr=1&sort=new&limit=25"),
    ]


def _referral_urls(slug: str, merchant_name: str) -> list[tuple[str, str]]:
    """Returns list of (source, url) for referral-code sources (first-order codes)."""
    import urllib.parse as _u
    q = _u.quote_plus(f"{merchant_name} referral")
    return [
        (PromoSource.REFERRAL.value,
         f"https://www.reddit.com/r/referralcodes/search.json?q={q}&restrict_sr=1&sort=new&limit=25"),
        (PromoSource.REFERRAL.value,
         f"https://refer.me/search?q={_u.quote_plus(merchant_name)}"),
        (PromoSource.REFERRAL.value,
         f"https://invitation.codes/search?q={_u.quote_plus(merchant_name)}"),
    ]


# Rakuten offer pages follow a predictable pattern.
def _rakuten_url(slug: str) -> str:
    return f"https://www.rakuten.com/{slug}.com"


def _topcashback_url(slug: str) -> str:
    return f"https://www.topcashback.com/{slug}/"


def _befrugal_url(slug: str) -> str:
    return f"https://www.befrugal.com/stores/{slug}/"


# Code extraction
CODE_RE = re.compile(
    r"(?:code|promo|coupon)[\s:=]*([A-Z0-9][A-Z0-9\-_]{3,20})",
    re.IGNORECASE,
)
PERCENT_RE = re.compile(r"(\d{1,2})\s*%\s*off", re.IGNORECASE)
DOLLAR_RE = re.compile(r"\$(\d{1,3})\s*off", re.IGNORECASE)
FREE_SHIPPING_RE = re.compile(r"free\s+shipping", re.IGNORECASE)
CASHBACK_RE = re.compile(
    r"(\d{1,2}(?:\.\d+)?)\s*%\s*(?:cash\s*back|cashback|back)",
    re.IGNORECASE,
)


class MealPromoHunterService:
    def __init__(self):
        self._scraper = get_meal_scraper()

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def hunt_for_service(self, service_id: str) -> dict:
        async with get_session() as session:
            svc = await session.get(MealServiceModel, service_id)
            if not svc:
                return {"status": "not_found"}

        host = self._extract_host(svc.website_url)
        discovered = 0
        updated = 0

        merchant_tokens = {
            svc.name.lower(),
            svc.slug.lower(),
            svc.slug.replace("-", "").lower(),
            host.split(".")[0].lower(),
        }
        merchant_tokens = {t for t in merchant_tokens if len(t) >= 4}

        html_urls = _aggregator_urls(svc.slug, host, svc.website_url)
        json_urls = _json_api_urls(svc.slug, host, svc.name)
        ref_urls = _referral_urls(svc.slug, svc.name)

        # HTML tier: scrape in parallel, then LLM-extract in parallel
        html_scrapes = await asyncio.gather(
            *(self._scraper.scrape(url) for _, url in html_urls),
            return_exceptions=True,
        )
        extract_tasks = []
        keep: list[tuple[str, str, str]] = []  # (source, url, markdown)
        for (source, url), scraped in zip(html_urls, html_scrapes):
            if isinstance(scraped, Exception):
                continue
            if scraped.get("status") != "ok":
                continue
            md = scraped.get("markdown") or ""
            if len(md) < 1000:
                continue
            keep.append((source, url, md))
            extract_tasks.append(
                self._extract_codes_llm(md, svc.name, svc.slug)
            )
        extracted_lists = await asyncio.gather(*extract_tasks, return_exceptions=True)

        for (source, url, md), codes in zip(keep, extracted_lists):
            if isinstance(codes, Exception) or not codes:
                codes = self._extract_codes(md, merchant_tokens)
            for code_info in codes:
                try:
                    was_new = await self._upsert_promo(
                        service_id=service_id,
                        service_slug=svc.slug,
                        source=source,
                        source_url=url,
                        code=code_info["code"],
                        discount_type=code_info["discount_type"],
                        discount_value=code_info["value"],
                        description=code_info.get("description"),
                    )
                    if was_new:
                        discovered += 1
                    else:
                        updated += 1
                except Exception as e:
                    logger.debug(
                        "promo_upsert_failed", service=svc.slug, error=str(e)
                    )

        # JSON tier: Capital One Shopping + Reddit — direct-parse, no LLM
        json_results = await asyncio.gather(
            *(
                self._hunt_json_source(source, url, svc.name, svc.slug)
                for source, url in json_urls
            ),
            return_exceptions=True,
        )
        for (source, url), items in zip(json_urls, json_results):
            if isinstance(items, Exception) or not items:
                continue
            for code_info in items:
                try:
                    was_new = await self._upsert_promo(
                        service_id=service_id,
                        service_slug=svc.slug,
                        source=source,
                        source_url=url,
                        code=code_info.get("code"),
                        discount_type=code_info.get("discount_type", "percent"),
                        discount_value=code_info.get("value", 0.0),
                        description=code_info.get("description"),
                    )
                    if was_new:
                        discovered += 1
                    else:
                        updated += 1
                except Exception as e:
                    logger.debug("promo_upsert_failed", service=svc.slug, error=str(e))

        # Referral tier — same JSON pipeline but flagged as referral
        ref_results = await asyncio.gather(
            *(
                self._hunt_json_source(source, url, svc.name, svc.slug, is_referral=True)
                for source, url in ref_urls
            ),
            return_exceptions=True,
        )
        for (source, url), items in zip(ref_urls, ref_results):
            if isinstance(items, Exception) or not items:
                continue
            for code_info in items:
                try:
                    was_new = await self._upsert_promo(
                        service_id=service_id,
                        service_slug=svc.slug,
                        source=source,
                        source_url=url,
                        code=code_info.get("code"),
                        discount_type=code_info.get("discount_type", "dollar"),
                        discount_value=code_info.get("value", 30.0),
                        description=code_info.get("description"),
                        is_referral=True,
                        new_customer_only=True,
                    )
                    if was_new:
                        discovered += 1
                    else:
                        updated += 1
                except Exception as e:
                    logger.debug("referral_upsert_failed", service=svc.slug, error=str(e))

        # Rakuten Advertising API (env-gated; skipped when not configured)
        if self._rakuten_advertising_enabled():
            try:
                rakuten_items = await self._hunt_rakuten_advertising(svc.name, svc.slug)
                for code_info in rakuten_items:
                    was_new = await self._upsert_promo(
                        service_id=service_id,
                        service_slug=svc.slug,
                        source=PromoSource.RAKUTEN_ADVERTISING.value,
                        source_url="https://api.linksynergy.com/coupon/1.0",
                        code=code_info.get("code"),
                        discount_type=code_info.get("discount_type", "percent"),
                        discount_value=code_info.get("value", 0.0),
                        description=code_info.get("description"),
                    )
                    if was_new:
                        discovered += 1
                    else:
                        updated += 1
            except Exception as e:
                logger.debug("rakuten_advertising_failed", service=svc.slug, error=str(e))

        # Cashback portal hunt (parallel across 3 portals inside _hunt_portals)
        portals_found = await self._hunt_portals(svc.id, svc.slug)

        logger.info(
            "promo_hunt_complete",
            service=svc.slug,
            discovered=discovered,
            updated=updated,
            portals=portals_found,
        )
        return {
            "status": "ok",
            "service": svc.slug,
            "discovered": discovered,
            "updated": updated,
            "portals_refreshed": portals_found,
        }

    async def hunt_all(self) -> dict:
        async with get_session() as session:
            services = (
                await session.execute(
                    select(MealServiceModel).where(MealServiceModel.status == "tracked")
                )
            ).scalars().all()

        totals = {"services": len(services), "discovered": 0, "updated": 0, "portals": 0}
        # Run services in batches so we parallelize but don't fire off 100+
        # concurrent LLM calls at once.
        BATCH = 5
        for i in range(0, len(services), BATCH):
            batch = services[i : i + BATCH]
            results = await asyncio.gather(
                *(self.hunt_for_service(s.id) for s in batch),
                return_exceptions=True,
            )
            for s, r in zip(batch, results):
                if isinstance(r, Exception):
                    logger.warning("promo_hunt_failed", service=s.slug, error=str(r))
                    continue
                totals["discovered"] += r.get("discovered", 0)
                totals["updated"] += r.get("updated", 0)
                totals["portals"] += r.get("portals_refreshed", 0)
        return totals

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # JSON-API sources (Capital One Shopping, Reddit, referral sites)
    # ------------------------------------------------------------------

    async def _hunt_json_source(
        self,
        source: str,
        url: str,
        merchant_name: str,
        merchant_slug: str,
        *,
        is_referral: bool = False,
    ) -> list[dict]:
        """Fetch a JSON endpoint and extract promo/referral codes.

        Handles Capital One Shopping (dedicated JSON), Reddit search.json, and
        referral aggregator pages. Returns a list of extracted code dicts
        compatible with _upsert_promo.
        """
        import aiohttp
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=25)
            ) as session:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Zero-MealManager/1.0)",
                    "Accept": "application/json, text/plain, */*",
                }
                async with session.get(url, headers=headers, allow_redirects=True) as resp:
                    if resp.status >= 400:
                        return []
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        # Referral sites often return HTML; fall back to LLM
                        body = await resp.text(errors="ignore")
                        if len(body) < 500:
                            return []
                        extracted = await self._extract_codes_llm(
                            body, merchant_name, merchant_slug
                        )
                        if is_referral:
                            for e in extracted:
                                e.setdefault("description", e.get("description") or f"{merchant_name} referral")
                        return extracted
        except Exception as e:
            logger.debug("json_source_fetch_failed", source=source, url=url, error=str(e))
            return []

        if source == PromoSource.CAPITAL_ONE_SHOPPING.value:
            return self._parse_capital_one_shopping(data)
        if source == PromoSource.REDDIT.value:
            return await self._parse_reddit_search(data, merchant_name, merchant_slug)
        if source == PromoSource.REFERRAL.value:
            return await self._parse_reddit_search(
                data, merchant_name, merchant_slug, referral=True
            )
        return []

    @staticmethod
    def _parse_capital_one_shopping(data: Any) -> list[dict]:
        """Parse the Capital One Shopping merchant/offers JSON envelope."""
        out: list[dict] = []
        offers = (data or {}).get("offers") if isinstance(data, dict) else None
        if not isinstance(offers, list):
            return out
        for o in offers:
            if not isinstance(o, dict):
                continue
            code = o.get("code") or o.get("couponCode")
            description = o.get("title") or o.get("description") or ""
            # Heuristic discount parsing from description text
            pct = re.search(r"(\d{1,2})\s*%\s*off", description, re.IGNORECASE)
            dollar = re.search(r"\$(\d{1,3})\s*off", description, re.IGNORECASE)
            free_ship = re.search(r"free\s+shipping", description, re.IGNORECASE)
            if pct:
                discount_type = "percent"
                value = float(pct.group(1))
            elif dollar:
                discount_type = "dollar"
                value = float(dollar.group(1))
            elif free_ship:
                discount_type = "free_shipping"
                value = 0.0
            else:
                continue
            out.append({
                "code": code.strip().upper() if isinstance(code, str) and code.strip() else None,
                "discount_type": discount_type,
                "value": value,
                "description": description[:200],
            })
        return out

    async def _parse_reddit_search(
        self,
        data: Any,
        merchant_name: str,
        merchant_slug: str,
        *,
        referral: bool = False,
    ) -> list[dict]:
        """Parse Reddit search.json and LLM-extract codes from post titles+bodies."""
        if not isinstance(data, dict):
            return []
        children = (data.get("data") or {}).get("children") or []
        if not children:
            return []
        # Concatenate top post titles + self-text, then LLM-extract
        chunks: list[str] = []
        for c in children[:25]:
            post = (c or {}).get("data") or {}
            title = post.get("title") or ""
            body = (post.get("selftext") or "")[:600]
            if title or body:
                chunks.append(f"{title}\n{body}")
        blob = "\n---\n".join(chunks)
        if len(blob) < 200:
            return []
        # For referrals, we deliberately set a default dollar value when LLM
        # doesn't give one (meal-kit referrals are almost always $30-50 off).
        extracted = await self._extract_codes_llm(blob, merchant_name, merchant_slug)
        if referral:
            for e in extracted:
                if not e.get("value") or e["value"] < 5:
                    e["discount_type"] = "dollar"
                    e["value"] = 30.0
        return extracted

    # ------------------------------------------------------------------
    # Rakuten Advertising Coupon Web Service (env-gated)
    # ------------------------------------------------------------------

    def _rakuten_advertising_enabled(self) -> bool:
        import os
        return bool(
            os.getenv("RAKUTEN_ADVERTISING_TOKEN")
            or (os.getenv("RAKUTEN_ADVERTISING_USERNAME") and os.getenv("RAKUTEN_ADVERTISING_PASSWORD"))
        )

    async def _hunt_rakuten_advertising(
        self, merchant_name: str, merchant_slug: str
    ) -> list[dict]:
        """Query Rakuten Advertising Coupon Web Service 1.0 (once configured).

        Requires approved publisher account. Returns [] when disabled or
        merchant not in the Rakuten catalog.
        """
        import os, aiohttp
        token = os.getenv("RAKUTEN_ADVERTISING_TOKEN")
        if not token:
            # Token exchange flow (if only user+pass available) is out of scope for v1
            return []
        # The Coupon Web Service expects a merchant search by name
        url = (
            "https://api.linksynergy.com/coupon/1.0"
            f"?network=1&resultsperpage=20&category=All&promotiontype=All&cat=&keyword="
            f"{merchant_name}"
        )
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status >= 400:
                        return []
                    # Response is XML historically; newer endpoints return JSON.
                    content_type = resp.headers.get("content-type", "")
                    if "json" in content_type:
                        data = await resp.json(content_type=None)
                        return self._parse_rakuten_advertising_json(data, merchant_name)
                    body = await resp.text(errors="ignore")
                    return self._parse_rakuten_advertising_xml(body, merchant_name)
        except Exception as e:
            logger.debug("rakuten_advertising_fetch_failed", error=str(e))
            return []

    @staticmethod
    def _parse_rakuten_advertising_json(data: Any, merchant_name: str) -> list[dict]:
        out: list[dict] = []
        coupons = (data or {}).get("couponfeed", {}).get("link", []) if isinstance(data, dict) else []
        if isinstance(coupons, dict):
            coupons = [coupons]
        for c in coupons or []:
            adv_name = str(c.get("advertisername", "")).lower()
            if merchant_name.lower() not in adv_name:
                continue
            code = c.get("couponcode")
            desc = c.get("offerdescription") or c.get("offerstartdate") or ""
            pct = re.search(r"(\d{1,2})\s*%", str(desc))
            dollar = re.search(r"\$(\d{1,3})", str(desc))
            if pct:
                d_type, value = "percent", float(pct.group(1))
            elif dollar:
                d_type, value = "dollar", float(dollar.group(1))
            else:
                continue
            out.append({
                "code": code.strip().upper() if isinstance(code, str) and code.strip() else None,
                "discount_type": d_type,
                "value": value,
                "description": str(desc)[:200],
            })
        return out

    @staticmethod
    def _parse_rakuten_advertising_xml(body: str, merchant_name: str) -> list[dict]:
        # Extremely lenient XML parse — we just look for <offerdescription> blocks
        out: list[dict] = []
        items = re.findall(
            r"<advertisername>([^<]+)</advertisername>[\s\S]*?"
            r"<offerdescription>([^<]+)</offerdescription>[\s\S]*?"
            r"(?:<couponcode>([^<]*)</couponcode>)?",
            body,
            re.IGNORECASE,
        )
        for adv, desc, code in items:
            if merchant_name.lower() not in adv.lower():
                continue
            pct = re.search(r"(\d{1,2})\s*%", desc)
            dollar = re.search(r"\$(\d{1,3})", desc)
            if pct:
                d_type, value = "percent", float(pct.group(1))
            elif dollar:
                d_type, value = "dollar", float(dollar.group(1))
            else:
                continue
            out.append({
                "code": code.strip().upper() if code and code.strip() else None,
                "discount_type": d_type,
                "value": value,
                "description": desc[:200],
            })
        return out

    def _extract_host(self, url: str) -> str:
        from urllib.parse import urlparse
        p = urlparse(url)
        return (p.netloc or url).replace("www.", "")

    async def _extract_codes_llm(
        self, markdown: str, merchant_name: str, merchant_slug: str
    ) -> list[dict]:
        """Ask the LLM to extract promo codes for this specific merchant.

        Aggregator pages interleave the target merchant's codes with
        sidebar widgets for unrelated brands. Regex can't tell the
        difference reliably. The LLM can.

        Returns empty list on any error so the caller falls back to regex.
        """
        if get_unified_llm_client is None or not markdown:
            return []

        # Truncate to ~8k chars — enough for the top-of-page merchant
        # section where real promos live; avoids burning tokens on
        # footer navigation / sidebar walls.
        trimmed = markdown[:8000]

        system = (
            "You extract promo codes for a specific merchant from a coupon "
            "aggregator page. You ONLY return promos that apply to the "
            "named merchant. You reject offers for other brands, even if "
            "they appear on the same page."
        )
        user = f'''Page is about merchant: "{merchant_name}" (slug: {merchant_slug}).

Extract promo codes ONLY for {merchant_name}. Ignore any offers for
OTHER brands (SHEIN, DoorDash, Target, Amazon, etc.) that may appear
in sidebars on this page.

Return a JSON object with a single key "promos" holding an array.
Each item:
  code: string or null (literal code like "SAVE20", null if auto-apply)
  discount_type: "percent" | "dollar" | "free_shipping" | "bogo"
  value: number (percent as 0-100; dollar as USD; 0 for free_shipping/bogo)
  description: short string (under 120 chars)
  new_customer_only: boolean
  stackable: boolean (usually false)

If no clear promos for {merchant_name}, return {{"promos": []}}.
Do not invent codes. Do not include offers whose description starts
with a different brand name.

Page content:
---
{trimmed}
---

Return only JSON, no prose.'''

        try:
            client = get_unified_llm_client()
            raw = await client.chat(
                prompt=user,
                system=system,
                task_type="meal_promo_extract",
                temperature=0.0,
                max_tokens=1500,
                json_mode=True,
            )
        except Exception as e:
            logger.debug("promo_llm_extract_error", error=str(e), merchant=merchant_slug)
            return []

        # Parse — handle both bare array and object-with-key formats
        import json as _json
        try:
            data = _json.loads(raw)
        except Exception:
            # Strip common ```json``` fences and retry
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

        cleaned: list[dict] = []
        for p in promos:
            if not isinstance(p, dict):
                continue
            d_type = p.get("discount_type") or ""
            if d_type not in {"percent", "dollar", "free_shipping", "bogo"}:
                continue
            try:
                val = float(p.get("value") or 0)
            except (TypeError, ValueError):
                continue
            code = p.get("code")
            if code and not isinstance(code, str):
                code = None
            if code:
                code = code.strip().upper()
                # Reject obvious nonsense codes
                if len(code) < 3 or len(code) > 30:
                    code = None
            description = p.get("description") or ""
            if len(description) > 300:
                description = description[:300]
            cleaned.append({
                "code": code,
                "discount_type": d_type,
                "value": val,
                "description": description,
            })
        logger.info(
            "promo_llm_extracted",
            merchant=merchant_slug,
            found=len(cleaned),
            raw_items=len(promos),
        )
        return cleaned

    @staticmethod
    def _strip_urls(line: str) -> str:
        """Drop markdown-link URLs and bare http URLs so visible-text
        substring checks aren't tricked by URL query-parameter content.

        Handles nested markdown like [![image](url)](url) by iterating
        the inner-to-outer link pattern until no URLs remain.
        """
        prev = None
        cur = line
        # Iterate because nested [...]([...](url)) needs repeated passes
        for _ in range(5):
            if cur == prev:
                break
            prev = cur
            # ![...](url) — image tag
            cur = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", cur)
            # [...](url) — link
            cur = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", cur)
        # Bare http URLs
        cur = re.sub(r"https?://\S+", " ", cur)
        # Collapse whitespace
        return re.sub(r"\s+", " ", cur).strip()

    def _extract_codes(
        self, markdown: str, merchant_tokens: Optional[set[str]] = None
    ) -> list[dict]:
        """Regex extraction with merchant-proximity gating.

        On aggregator pages the target-merchant section is interleaved with
        sidebar widgets for unrelated brands. We only trust a promo line when
        the surrounding visible text mentions the target merchant. We strip
        markdown link URLs before checking because URL query strings embed
        the source page URL (which always contains the target slug, defeating
        naive substring checks).
        """
        found: dict[str, dict] = {}
        raw_lines = markdown.splitlines()
        # Build a parallel "text-only" view of each line: drop URLs inside
        # parentheses and bare URLs, keep only visible text.
        text_lines = [self._strip_urls(ln).lower() for ln in raw_lines]

        def _has_merchant(idx: int) -> bool:
            if not merchant_tokens:
                return True
            lo = max(0, idx - 2)
            hi = min(len(text_lines), idx + 3)
            ctx = " ".join(text_lines[lo:hi])
            return any(tok in ctx for tok in merchant_tokens)

        # Also skip any line that names a known non-target brand (common
        # sidebar noise on RetailMeNot, CouponFollow, etc.)
        KNOWN_OTHER_BRANDS = {
            "shein", "walgreens", "southwest", "domino", "kohl", "papa john",
            "target", "old navy", "doordash", "uber eats", "grubhub",
            "amazon", "walmart", "macy", "nike", "adidas", "verizon", "at&t",
            "best buy", "home depot", "lowes", "starbucks", "sephora",
            "ulta", "chewy", "expedia", "hotels.com", "booking.com",
        }

        # Assume the page is merchant-scoped (we hit a merchant-specific
        # URL like /view/<slug>.com). Accept every promo-looking line
        # UNLESS its visible text names a known competitor brand
        # without also naming our merchant. This flips the previous
        # strict proximity rule, which over-rejected because aggregator
        # pages don't repeat the merchant name near every promo.
        for idx, raw in enumerate(raw_lines):
            text_line = text_lines[idx]
            # Reject if line names another brand and NOT ours
            if any(b in text_line for b in KNOWN_OTHER_BRANDS):
                if not (merchant_tokens and any(t in text_line for t in merchant_tokens)):
                    continue
            code_match = CODE_RE.search(raw)
            pct = PERCENT_RE.search(raw)
            dollar = DOLLAR_RE.search(raw)
            shipping = FREE_SHIPPING_RE.search(raw)

            if not (code_match or shipping):
                continue
            line = raw

            code = code_match.group(1).upper() if code_match else None
            # Filter junk matches. Real promo codes almost always contain
            # either a digit, or two+ distinct "code-like" features
            # (underscore, hyphen, unusual casing). Plain dictionary words
            # like DURING, CODES, REQUIRED, OFFER are false positives.
            if code:
                code_lower = code.lower()
                has_digit = any(c.isdigit() for c in code)
                has_separator = "-" in code or "_" in code
                is_common_word = code_lower in {
                    "offer", "offers", "shop", "here", "now", "click", "save", "deal",
                    "code", "codes", "coupon", "coupons", "promo", "promos", "free",
                    "during", "required", "needed", "apply", "use", "get", "buy",
                    "this", "that", "from", "with", "when", "where", "what", "best",
                    "new", "cust", "customer", "sale", "today", "limited", "time",
                    "only", "more", "first", "orders", "order",
                }
                # Require at least one "code-like" signal and not a common word
                if is_common_word or not (has_digit or has_separator):
                    code = None

            if pct:
                d_type = PromoDiscountType.PERCENT.value
                value = float(pct.group(1))
            elif dollar:
                d_type = PromoDiscountType.DOLLAR.value
                value = float(dollar.group(1))
            elif shipping:
                d_type = PromoDiscountType.FREE_SHIPPING.value
                value = 0.0
            else:
                continue

            key = code or f"auto_{d_type}_{value}"
            if key not in found or found[key]["value"] < value:
                found[key] = {
                    "code": code,
                    "discount_type": d_type,
                    "value": value,
                    "description": line.strip()[:200],
                }
        return list(found.values())

    # ------------------------------------------------------------------
    # Upsert
    # ------------------------------------------------------------------

    async def _upsert_promo(
        self,
        *,
        service_id: Optional[str],
        service_slug: str,
        source: str,
        source_url: str,
        code: Optional[str],
        discount_type: str,
        discount_value: float,
        description: Optional[str],
        is_referral: bool = False,
        new_customer_only: bool = False,
    ) -> bool:
        """Returns True if a new row was inserted."""
        async with get_session() as session:
            stmt = select(MealPromoCodeModel).where(
                MealPromoCodeModel.service_id == service_id,
                MealPromoCodeModel.source == source,
                MealPromoCodeModel.discount_type == discount_type,
                MealPromoCodeModel.discount_value == discount_value,
            )
            if code:
                stmt = stmt.where(MealPromoCodeModel.code == code)
            existing = (await session.execute(stmt)).scalar_one_or_none()
            now = datetime.utcnow()
            if existing:
                existing.times_seen = (existing.times_seen or 1) + 1
                existing.last_seen_at = now
                if description and not existing.description:
                    existing.description = description
                return False
            key = f"{service_id or 'generic'}|{source}|{code or ''}|{discount_type}|{discount_value}"
            pid = "promo_" + hashlib.sha1(key.encode()).hexdigest()[:20]
            session.add(MealPromoCodeModel(
                id=pid,
                code=code,
                service_id=service_id,
                service_slug_hint=service_slug,
                source=source,
                source_url=source_url,
                discount_type=discount_type,
                discount_value=discount_value,
                description=description,
                stackable=False,
                is_referral=is_referral,
                new_customer_only=new_customer_only or is_referral,
                expires_at=now + timedelta(days=14),  # default freshness window
            ))
            return True

    async def _hunt_portals(self, service_id: str, slug: str) -> int:
        """Scrape Rakuten / TopCashback / BeFrugal for merchant cashback %."""
        found = 0
        for portal_enum, url_fn in [
            (RebatePortal.RAKUTEN, _rakuten_url),
            (RebatePortal.TOPCASHBACK, _topcashback_url),
            (RebatePortal.BEFRUGAL, _befrugal_url),
        ]:
            url = url_fn(slug)
            try:
                scraped = await self._scraper.scrape(url)
                if scraped.get("status") != "ok" or len(scraped["markdown"]) < 200:
                    continue
                match = CASHBACK_RE.search(scraped["markdown"])
                if not match:
                    continue
                pct = float(match.group(1))
                await self._upsert_portal(
                    service_id=service_id,
                    merchant_name=slug,
                    portal=portal_enum.value,
                    cashback_percent=pct,
                    source_url=url,
                )
                found += 1
            except Exception as e:
                logger.debug("portal_hunt_failed", portal=portal_enum.value, slug=slug, error=str(e))
        return found

    async def _upsert_portal(
        self,
        *,
        service_id: str,
        merchant_name: str,
        portal: str,
        cashback_percent: float,
        source_url: str,
    ):
        async with get_session() as session:
            stmt = select(MealRebatePortalOfferModel).where(
                MealRebatePortalOfferModel.portal == portal,
                MealRebatePortalOfferModel.merchant_name == merchant_name,
                MealRebatePortalOfferModel.new_customer_only == False,  # noqa
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()
            now = datetime.utcnow()
            if existing:
                existing.cashback_percent = cashback_percent
                existing.service_id = service_id
                existing.source_url = source_url
                existing.last_seen_at = now
                return
            key = f"{portal}|{merchant_name}"
            rid = "rebate_" + hashlib.sha1(key.encode()).hexdigest()[:20]
            session.add(MealRebatePortalOfferModel(
                id=rid,
                portal=portal,
                service_id=service_id,
                merchant_name=merchant_name,
                cashback_percent=cashback_percent,
                source_url=source_url,
                new_customer_only=False,
            ))


_singleton: Optional[MealPromoHunterService] = None


def get_meal_promo_hunter() -> MealPromoHunterService:
    global _singleton
    if _singleton is None:
        _singleton = MealPromoHunterService()
    return _singleton
