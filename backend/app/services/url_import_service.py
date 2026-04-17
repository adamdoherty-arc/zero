"""
URL Import Service for TikTok Shop products.
Imports products from pasted URLs (Amazon, AliExpress, TikTok Shop, etc.)
by fetching metadata and extracting product info.
"""

import ipaddress
import re
import socket
from typing import Dict, Optional
from urllib.parse import urlparse

import httpx
import structlog

from app.infrastructure.json_utils import extract_json_from_text, llm_retry, sanitize_for_prompt
from app.infrastructure.langchain_adapter import get_zero_chat_model
from app.models.tiktok_shop import TikTokProduct, TikTokProductCreate
from app.services.tiktok_shop_service import get_tiktok_shop_service
from app.services.searxng_service import get_searxng_service

logger = structlog.get_logger()


class UrlImportService:
    """Import TikTok Shop products from URLs."""

    BLOCKED_HOSTNAMES = {"localhost", "host.docker.internal", "kubernetes.default"}

    def __init__(self):
        from app.infrastructure.circuit_breaker import get_circuit_breaker
        self._breaker = get_circuit_breaker("url_import", failure_threshold=5, recovery_timeout=60.0)

    def _validate_url_safe(self, url: str) -> None:
        """Validate URL is safe to fetch (SSRF protection)."""
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")
        hostname = parsed.hostname
        if not hostname:
            raise ValueError("URL has no hostname")
        if hostname in self.BLOCKED_HOSTNAMES:
            raise ValueError(f"Blocked hostname: {hostname}")
        try:
            resolved = socket.getaddrinfo(hostname, None)
            for _, _, _, _, sockaddr in resolved:
                ip = ipaddress.ip_address(sockaddr[0])
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                    raise ValueError(f"URL resolves to non-public IP: {ip}")
        except socket.gaierror:
            raise ValueError(f"Cannot resolve hostname: {hostname}")

    def _detect_source(self, url: str) -> str:
        """Detect the source marketplace from a URL."""
        domain = urlparse(url).netloc.lower()
        if "amazon" in domain:
            return "amazon"
        if "aliexpress" in domain:
            return "aliexpress"
        if "tiktok.com" in domain and "/product/" in url.lower():
            return "tiktok_shop"
        if "alibaba" in domain:
            return "alibaba"
        if "cjdropshipping" in domain:
            return "cjdropshipping"
        return "generic"

    async def _fetch_opengraph_metadata(self, url: str) -> Dict:
        """Fetch Open Graph / meta tags from a URL."""
        try:
            self._validate_url_safe(url)
            return await self._breaker.call(self._do_fetch_og, url)
        except Exception as e:
            logger.warning("fetch_opengraph_failed", url=url, error=str(e))
            return {}

    async def _do_fetch_og(self, url: str) -> Dict:
        """Inner fetch, wrapped by circuit breaker."""
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ZeroBot/1.0)"},
        ) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return {}
            html = resp.text[:50000]  # limit parsing

            meta = {}
            # Extract og: tags
            og_patterns = {
                "title": r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)',
                "description": r'<meta\s+property=["\']og:description["\']\s+content=["\']([^"\']+)',
                "image": r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)',
                "price": r'<meta\s+property=["\']product:price:amount["\']\s+content=["\']([^"\']+)',
            }
            for key, pattern in og_patterns.items():
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    meta[key] = match.group(1)

            # Fallback to <title> tag
            if "title" not in meta:
                title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
                if title_match:
                    meta["title"] = title_match.group(1).strip()

            # Fallback to meta description
            if "description" not in meta:
                desc_match = re.search(
                    r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)',
                    html, re.IGNORECASE,
                )
                if desc_match:
                    meta["description"] = desc_match.group(1)

        return meta

    @llm_retry
    async def _do_llm_extract(self, prompt: str) -> dict:
        """Retryable LLM extraction call."""
        from app.infrastructure.unified_llm_client import get_unified_llm_client
        client = get_unified_llm_client()
        return await client.structured_chat(
            prompt=prompt,
            task_type="extraction",
            temperature=0.3,
            max_tokens=2048,
            output_schema={"name": "str", "description": "str", "price_min": None, "price_max": None, "category": "str", "niche": "str", "why_trending": "str"},
        )

    async def _extract_product_info_llm(self, page_content: str, source: str, url: str) -> Dict:
        """Use LLM to extract product information from page content."""
        try:
            safe_content = sanitize_for_prompt(page_content, max_length=3000)
            prompt = (
                f"Extract product information from this {source} page content.\n\n"
                f"URL: {url}\nContent: {safe_content}\n\n"
                f"Provide: name, description, price_min, price_max, category, niche, why_trending"
            )
            parsed = await self._do_llm_extract(prompt)
            if isinstance(parsed, dict):
                return parsed
        except Exception as e:
            logger.warning("llm_extract_failed", url=url, error=str(e))
        return {}

    async def import_from_url(self, url: str, run_research: bool = True) -> TikTokProduct:
        """Import a product from a URL.

        Strategy:
        1. Detect source marketplace
        2. Fetch Open Graph metadata (fast)
        3. If sparse, use SearXNG + LLM extraction (thorough)
        4. Create product record
        5. Optionally trigger full research pipeline
        """
        self._validate_url_safe(url)

        # Check for duplicate URL import
        shop_service = get_tiktok_shop_service()
        existing = await shop_service.find_product_by_url(url)
        if existing:
            logger.info("duplicate_url_import", url=url, existing_id=existing.id)
            return existing

        source = self._detect_source(url)
        logger.info("url_import_start", url=url, source=source)

        # Step 1: Try Open Graph metadata
        og_data = await self._fetch_opengraph_metadata(url)

        # Step 2: If OG data is sparse, use SearXNG for more context
        llm_data = {}
        if not og_data.get("title") or not og_data.get("description"):
            try:
                searxng = get_searxng_service()
                # Search for the URL content
                search_query = og_data.get("title", url)
                results = await searxng.search(search_query, num_results=3)
                if results:
                    combined = " ".join(
                        f"{r.title}: {r.snippet}" for r in results[:3] if hasattr(r, "snippet")
                    )
                    llm_data = await self._extract_product_info_llm(combined, source, url)
            except Exception as e:
                logger.warning("searxng_fallback_failed", url=url, error=str(e))

        # If we still have nothing, try LLM on OG data
        if not llm_data and og_data:
            combined = f"Title: {og_data.get('title', '')}. Description: {og_data.get('description', '')}"
            llm_data = await self._extract_product_info_llm(combined, source, url)

        # Merge data (OG takes precedence for title/image, LLM for niche/category)
        name = og_data.get("title") or llm_data.get("name") or f"Imported from {source}"
        # Clean common suffixes from titles
        for suffix in [" - Amazon.com", " | AliExpress", " - Walmart.com", " | TikTok Shop"]:
            if name.endswith(suffix):
                name = name[: -len(suffix)]

        description = og_data.get("description") or llm_data.get("description")
        image_url = og_data.get("image")

        # Parse price
        price_min = None
        price_max = None
        price_str = og_data.get("price") or str(llm_data.get("price_min", ""))
        if price_str:
            try:
                price_val = float(re.sub(r"[^\d.]", "", price_str))
                price_min = price_val
                price_max = llm_data.get("price_max") or price_val
            except (ValueError, TypeError):
                pass

        # Determine product type based on source
        product_type = "affiliate"
        if source in ("aliexpress", "alibaba", "cjdropshipping"):
            product_type = "dropship"

        # Build create request
        create_data = TikTokProductCreate(
            name=name[:500],
            category=llm_data.get("category", "general") or "general",
            niche=llm_data.get("niche"),
            description=description,
            source_url=url,
            marketplace_url=url,
            product_type=product_type,
            why_trending=llm_data.get("why_trending"),
            image_url=image_url,
            price_range_min=price_min,
            price_range_max=price_max,
            import_url=url,
            import_source=source,
        )

        shop_service = get_tiktok_shop_service()

        if run_research:
            product = await shop_service.add_and_research_product(create_data)
        else:
            product = await shop_service.create_product(create_data)

        # Set the import fields on the DB row directly since create_product may not pass them
        from app.infrastructure.database import get_session
        from app.db.models import TikTokProductModel
        from sqlalchemy import select
        async with get_session() as session:
            result = await session.execute(
                select(TikTokProductModel).where(TikTokProductModel.id == product.id)
            )
            row = result.scalar_one_or_none()
            if row:
                row.import_url = url
                row.import_source = source
                if image_url and not row.image_url:
                    row.image_url = image_url
                await session.flush()

        logger.info("url_import_complete", product_id=product.id, name=name, source=source)
        return await shop_service.get_product(product.id) or product


def get_url_import_service() -> UrlImportService:
    """Get URL import service instance."""
    return UrlImportService()
