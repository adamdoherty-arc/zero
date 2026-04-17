"""
TikTok Shop Research Agent Service.

Discovers trending TikTok Shop products (affiliate + dropship), scores market
opportunities, generates content ideas, and creates Legion tasks.
Follows the same pattern as ResearchService: singleton, SearXNG search,
3-layer scoring (heuristic -> LLM -> rules), pgvector embeddings.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from functools import lru_cache
import structlog
import uuid

from sqlalchemy import select, update, delete, func as sql_func

from app.infrastructure.database import get_session
from app.infrastructure.config import get_settings
from app.db.models import TikTokProductModel, ServiceConfigModel
from app.models.tiktok_shop import (
    TikTokProduct, TikTokProductCreate, TikTokProductUpdate,
    TikTokProductStatus, TikTokProductApproval,
    TikTokResearchCycleResult, TikTokShopStats,
)
from app.services.searxng_service import get_searxng_service
from app.infrastructure.json_utils import llm_retry
from app.infrastructure.langchain_adapter import get_zero_chat_model, get_structured_chat_model

logger = structlog.get_logger()

ZERO_PROJECT_ID = get_settings().zero_legion_project_id

def _get_search_queries() -> list:
    """Generate search queries with current year for freshness."""
    year = datetime.now().year
    return [
        # General trending
        f"tiktok shop best selling products {year}",
        f"trending tiktok shop products this week",
        f"tiktok made me buy it best products {year}",
        f"viral tiktok shop products this month",
        f"tiktok shop winning products high margin",
        f"most sold items tiktok shop today",
        # Category-specific
        f"tiktok shop top sellers beauty skincare",
        f"tiktok shop viral gadgets home kitchen",
        f"tiktok shop supplements protein fitness {year}",
        f"tiktok shop health wellness products trending",
        # Affiliate & dropship
        f"tiktok shop dropshipping winning products supplier",
        f"best tiktok shop affiliate products high commission",
        # Platform-specific
        f"aliexpress trending products {year} tiktok",
        f"amazon movers and shakers products {year}",
        f"shopify trending products tiktok {year}",
        # Viral content
        f"tiktokmademebuyit viral products {year}",
        f"tiktok viral products this week must have",
        f"most sold tiktok shop products {year} revenue",
        # Niche combos
        f"best beauty products for tiktok content {year}",
        f"trending home gadgets tiktok shop {year}",
        f"tiktok shop fashion accessories viral",
        f"tiktok shop pet products trending {year}",
        f"tiktok shop tech gadgets under $50 {year}",
        # Content creator angles
        f"what products are tiktok creators selling {year}",
        f"tiktok shop creator picks trending now",
        f"top tiktok shop products for content creators",
        # Cross-platform trending (Sprint 2)
        f"amazon movers and shakers best sellers today {year}",
        f"instagram reels viral products {year}",
        f"youtube shorts product review trending {year}",
        f"reddit what to sell online tiktok {year}",
        f"google trends rising products ecommerce {year}",
        f"shopify trending products to sell online {year}",
        # Affiliate marketplace specific
        f"tiktok shop affiliate marketplace best commission products {year}",
        f"tiktok shop high commission rate products for creators {year}",
        f"tiktok shop sample products free for creators {year}",
        f"kalodata tiktok shop best sellers commission {year}",
        f"shoplus tiktok trending products sales volume {year}",
        f"tiktok shop creator pilot program eligible products {year}",
        f"best tiktok affiliate products easy content {year}",
        f"tiktok shop products with free samples for affiliates {year}",
    ]

DEFAULT_NICHES = [
    "beauty", "home", "fitness", "pet", "kitchen",
    "tech accessories", "fashion", "baby", "outdoor",
    "supplements", "health", "wellness", "gaming", "food",
    "automotive", "stationery", "travel", "cleaning",
    "organization", "phone accessories", "skincare", "fragrance",
]

DEFAULT_CONFIG = {
    "llm": {
        "model": None,
        "temperature": 0.3,
        "max_tokens": 2500,
        "timeout": 180,
    },
    "daily": {
        "max_results_per_query": 10,
        "max_auto_tasks_per_cycle": 5,
        "high_opportunity_threshold": 60,
        "llm_score_threshold": 50,
    },
    "scoring_weights": {
        "trend": 0.30,
        "inverse_competition": 0.20,
        "margin": 0.25,
        "actionability": 0.25,
    },
    "retention": {
        "max_products": 2000,
    },
}

# Scoring keyword lists
TREND_SIGNALS = [
    "viral", "trending", "hot", "best seller", "top selling",
    "million views", "gmv", "fast growing", "popular", "sold out",
    "winning product", "tiktok made me buy", "best selling",
    "top product", "most sold", "high demand", "blowing up",
]
MARGIN_SIGNALS = [
    "high margin", "profit", "markup", "dropship", "wholesale",
    "commission", "affiliate", "earn", "revenue", "income",
    "high commission", "$", "price", "cheap", "budget",
    "under $20", "low cost",
]
COMPETITION_SIGNALS = [
    "saturated", "competitive", "crowded", "many sellers",
    "red ocean", "oversaturated",
]
ACTIONABILITY_SIGNALS = [
    "how to sell", "guide", "tutorial", "step by step", "supplier",
    "source", "listing", "promote", "tiktok shop seller",
    "product", "buy", "shop", "store", "order",
    "sell", "selling", "sold", "review", "unboxing",
]

# Month-aware seasonal keywords for scoring boost (month 1=Jan)
SEASONAL_MAP = {
    1: ["resolution", "fitness", "organization", "planner", "gym", "health", "wellness", "detox"],
    2: ["valentine", "gift", "romantic", "love", "couple", "date night", "heart"],
    3: ["spring", "gardening", "cleaning", "allergy", "outdoor", "fresh"],
    4: ["easter", "spring break", "travel", "garden", "earth day", "outdoor"],
    5: ["mother", "mom", "gift for her", "graduation", "memorial day", "summer prep"],
    6: ["father", "dad", "summer", "outdoor", "beach", "sunscreen", "pool"],
    7: ["summer", "beach", "outdoor", "bbq", "grill", "travel", "camping"],
    8: ["back to school", "school supplies", "college", "dorm", "fall prep"],
    9: ["fall", "autumn", "back to school", "pumpkin", "cozy", "football"],
    10: ["halloween", "costume", "spooky", "fall", "pumpkin", "cozy"],
    11: ["holiday", "gift", "christmas", "black friday", "cyber monday", "deal", "thanksgiving"],
    12: ["christmas", "gift", "stocking stuffer", "holiday", "new year", "winter", "cozy"],
}


class TikTokShopService:
    """TikTok Shop Research Agent."""

    @llm_retry
    async def _retry_structured_chat(self, client, **kwargs):
        """Retryable wrapper for LLM structured_chat calls."""
        return await client.structured_chat(**kwargs)

    def _generate_id(self, prefix: str = "ttp") -> str:
        return f"{prefix}-{uuid.uuid4().hex[:12]}"

    async def _get_config(self) -> Dict[str, Any]:
        try:
            async with get_session() as session:
                result = await session.execute(
                    select(ServiceConfigModel).where(
                        ServiceConfigModel.service_name == "tiktok_shop"
                    )
                )
                row = result.scalar_one_or_none()
                if row:
                    return {**DEFAULT_CONFIG, **row.config}
        except Exception:
            pass
        return DEFAULT_CONFIG

    # ============================================
    # CRUD
    # ============================================

    async def list_products(
        self,
        status: Optional[str] = None,
        niche: Optional[str] = None,
        min_score: Optional[float] = None,
        search: Optional[str] = None,
        product_type: Optional[str] = None,
        sort_by: str = "opportunity_score",
        sort_order: str = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> List[TikTokProduct]:
        limit = min(max(limit, 1), 200)
        offset = max(offset, 0)
        async with get_session() as session:
            query = select(TikTokProductModel).where(
                TikTokProductModel.archived_at.is_(None)
            )

            if status:
                query = query.where(TikTokProductModel.status == status)
            if niche:
                query = query.where(TikTokProductModel.niche == niche)
            if min_score is not None:
                query = query.where(TikTokProductModel.opportunity_score >= min_score)
            if product_type:
                query = query.where(TikTokProductModel.product_type == product_type)
            if search:
                term = f"%{search.lower()}%"
                query = query.where(
                    sql_func.lower(TikTokProductModel.name).like(term)
                    | sql_func.lower(sql_func.coalesce(TikTokProductModel.description, "")).like(term)
                    | sql_func.lower(sql_func.coalesce(TikTokProductModel.why_trending, "")).like(term)
                )

            sort_map = {
                "opportunity_score": TikTokProductModel.opportunity_score,
                "name": TikTokProductModel.name,
                "discovered_at": TikTokProductModel.discovered_at,
                "success_rating": TikTokProductModel.success_rating,
            }
            sort_col = sort_map.get(sort_by, TikTokProductModel.opportunity_score)
            query = query.order_by(sort_col.asc() if sort_order == "asc" else sort_col.desc())
            if offset > 0:
                query = query.offset(offset)
            query = query.limit(limit)

            result = await session.execute(query)
            rows = result.scalars().all()
            return [self._model_to_pydantic(r) for r in rows]

    async def get_product(self, product_id: str) -> Optional[TikTokProduct]:
        async with get_session() as session:
            result = await session.execute(
                select(TikTokProductModel).where(TikTokProductModel.id == product_id)
            )
            row = result.scalar_one_or_none()
            return self._model_to_pydantic(row) if row else None

    async def create_product(self, data: TikTokProductCreate) -> TikTokProduct:
        product_id = self._generate_id()
        async with get_session() as session:
            row = TikTokProductModel(
                id=product_id,
                name=data.name,
                category=data.category,
                niche=data.niche,
                description=data.description,
                source_url=data.source_url,
                marketplace_url=data.marketplace_url,
                product_type=data.product_type.value if data.product_type else "unknown",
                tags=data.tags or [],
                price_range_min=data.price_range_min,
                price_range_max=data.price_range_max,
                commission_rate=data.commission_rate,
                source_article_title=data.source_article_title,
                source_article_url=data.source_article_url,
                is_extracted=data.is_extracted,
                why_trending=data.why_trending,
                estimated_price_range=data.estimated_price_range,
                affiliate_link=getattr(data, "affiliate_link", None),
                tiktok_shop_url=getattr(data, "tiktok_shop_url", None),
                import_url=getattr(data, "import_url", None),
                import_source=getattr(data, "import_source", None),
            )
            if data.image_url:
                row.image_url = data.image_url
            session.add(row)
            await session.flush()
            return self._model_to_pydantic(row)

    async def update_product(
        self, product_id: str, updates: TikTokProductUpdate
    ) -> Optional[TikTokProduct]:
        async with get_session() as session:
            result = await session.execute(
                select(TikTokProductModel).where(TikTokProductModel.id == product_id)
            )
            row = result.scalar_one_or_none()
            if not row:
                return None

            update_data = updates.model_dump(exclude_unset=True)
            if "status" in update_data and update_data["status"]:
                update_data["status"] = update_data["status"].value
            if "product_type" in update_data and update_data["product_type"]:
                update_data["product_type"] = update_data["product_type"].value

            for key, value in update_data.items():
                setattr(row, key, value)

            await session.flush()
            return self._model_to_pydantic(row)

    async def find_product_by_url(self, url: str) -> Optional[TikTokProduct]:
        """Find an existing product by import/marketplace/source URL."""
        async with get_session() as session:
            from sqlalchemy import or_
            result = await session.execute(
                select(TikTokProductModel).where(
                    or_(
                        TikTokProductModel.import_url == url,
                        TikTokProductModel.marketplace_url == url,
                        TikTokProductModel.source_url == url,
                    )
                ).where(
                    TikTokProductModel.archived_at.is_(None)
                ).limit(1)
            )
            row = result.scalar_one_or_none()
            return self._model_to_pydantic(row) if row else None

    async def delete_product(self, product_id: str) -> bool:
        """Soft delete: set archived_at instead of hard DELETE."""
        async with get_session() as session:
            result = await session.execute(
                select(TikTokProductModel).where(TikTokProductModel.id == product_id)
            )
            row = result.scalar_one_or_none()
            if not row:
                return False
            row.archived_at = datetime.now(timezone.utc)
            row.status = "rejected"
            await session.flush()
            return True

    # ============================================
    # APPROVAL QUEUE
    # ============================================

    async def list_pending(self, limit: int = 50, offset: int = 0) -> List[TikTokProduct]:
        """List products pending approval, ordered by opportunity score."""
        return await self.list_products(status="pending_approval", limit=limit, offset=offset)

    async def batch_approve(self, product_ids: List[str]) -> int:
        """Approve multiple products. Returns count of approved products."""
        approved = 0
        now = datetime.now(timezone.utc)
        async with get_session() as session:
            for pid in product_ids:
                result = await session.execute(
                    select(TikTokProductModel).where(TikTokProductModel.id == pid)
                )
                row = result.scalar_one_or_none()
                if row and row.status in ("pending_approval", "discovered"):
                    row.status = "approved"
                    row.approved_at = now
                    row.rejected_at = None
                    row.rejection_reason = None
                    approved += 1
        logger.info("tiktok_batch_approved", count=approved, total_requested=len(product_ids))

        # Record to brain
        try:
            from app.services.zero_brain_service import get_zero_brain_service
            brain = get_zero_brain_service()
            await brain.record_interaction_outcome(
                domain="content", action_type="product_approval",
                strategy_used="batch_approve",
                actual_score=min(100, approved * 20),
                metrics={"approved": approved, "requested": len(product_ids)},
            )
        except Exception:
            pass

        # Auto-enrich approved products if enabled
        config = await self._get_config()
        if config.get("auto_enrichment_enabled", True) and approved > 0:
            for pid in product_ids:
                try:
                    await self.enrich_product(pid)
                except Exception as e:
                    logger.warning("auto_enrich_after_approve_failed", product_id=pid, error=str(e))

        return approved

    async def batch_reject(self, product_ids: List[str], reason: Optional[str] = None) -> int:
        """Reject multiple products. Returns count of rejected products."""
        rejected = 0
        now = datetime.now(timezone.utc)
        async with get_session() as session:
            for pid in product_ids:
                result = await session.execute(
                    select(TikTokProductModel).where(TikTokProductModel.id == pid)
                )
                row = result.scalar_one_or_none()
                if row and row.status in ("pending_approval", "discovered"):
                    row.status = "rejected"
                    row.rejected_at = now
                    row.rejection_reason = reason
                    rejected += 1
        logger.info("tiktok_batch_rejected", count=rejected, reason=reason)
        return rejected

    async def auto_approve_high_confidence(self, threshold: float = None) -> int:
        """Auto-approve products with opportunity score >= threshold."""
        if threshold is None:
            config = await self._get_config()
            threshold = config.get("auto_approve_threshold", 85.0)
        async with get_session() as session:
            result = await session.execute(
                select(TikTokProductModel).where(
                    TikTokProductModel.status == "pending_approval",
                    TikTokProductModel.opportunity_score >= threshold,
                )
            )
            rows = result.scalars().all()
            now = datetime.now(timezone.utc)
            for row in rows:
                row.status = "approved"
                row.approved_at = now
            count = len(rows)

        if count > 0:
            logger.info("tiktok_auto_approved", count=count, threshold=threshold)
        return count

    # ============================================
    # RESEARCH EXECUTION
    # ============================================

    async def _extract_products_from_articles(
        self, search_results: list
    ) -> List[Dict[str, Any]]:
        """Use LLM to extract actual sellable products from SearXNG article results.

        Processes articles in batches of 10 to avoid context overflow.
        Returns list of dicts with: name, category, estimated_price_range,
        why_trending, source_article_title, source_article_url.
        """
        if not search_results:
            return []

        # Build article summaries for LLM
        articles = []
        for r in search_results[:60]:  # Increased from 30 to 60
            title = r.title if hasattr(r, "title") else str(r)
            snippet = r.snippet if hasattr(r, "snippet") else ""
            url = r.url if hasattr(r, "url") else ""
            articles.append({"title": title, "snippet": snippet[:300], "url": url})

        all_products = []
        seen_names = set()
        batch_size = 10

        # Process in batches of 10 articles
        for batch_start in range(0, len(articles), batch_size):
            batch = articles[batch_start:batch_start + batch_size]
            try:
                import json
                from app.infrastructure.unified_llm_client import get_unified_llm_client

                client = get_unified_llm_client()

                articles_text = "\n\n".join(
                    f"Article: {a['title']}\nSnippet: {a['snippet']}\nURL: {a['url']}"
                    for a in batch
                )

                prompt = (
                    "You are a TikTok Shop product analyst. Below are search result articles about "
                    "trending TikTok products.\n\n"
                    "Extract ACTUAL SELLABLE PRODUCTS mentioned in these articles. "
                    "Do NOT return article titles as products. Extract real product names like "
                    "'LED Face Mask', 'Portable Blender', 'Cloud Slides', etc.\n\n"
                    "For each product, provide:\n"
                    "- name: The actual product name (short, specific, under 50 chars)\n"
                    "- category: Product category (beauty, kitchen, tech, fitness, fashion, home, pet, etc.)\n"
                    "- estimated_price_range: e.g. '$15-$30'\n"
                    "- why_trending: One SHORT sentence\n\n"
                    "Extract up to 10 unique products from these articles.\n\n"
                    f"---ARTICLES---\n{articles_text}"
                )

                products = await self._retry_structured_chat(
                    client,
                    prompt=prompt,
                    system="You extract real sellable product names from articles. Return ONLY a JSON array.",
                    task_type="extraction",
                    temperature=0.2,
                    max_tokens=4096,
                    output_schema=[{"name": "str", "category": "str", "estimated_price_range": "str", "why_trending": "str"}],
                )

                if isinstance(products, list):
                    for p in products:
                        name = p.get("name", "")
                        if not name:
                            continue
                        name_lower = name.lower().strip()
                        # Skip names that are clearly article titles
                        article_patterns = [
                            "top products", "best selling", "here are",
                            "list of", "trending products on", "how to",
                            "guide", "tiktok made me", "this week's",
                            "discover", "best products to", "what products",
                        ]
                        if len(name) > 80 or any(pat in name_lower for pat in article_patterns):
                            logger.debug("tiktok_skipped_article_title", name=name[:80])
                            continue
                        # Deduplicate within extraction
                        if name_lower in seen_names:
                            continue
                        seen_names.add(name_lower)
                        all_products.append({
                            "name": name[:500],
                            "category": p.get("category", "general"),
                            "estimated_price_range": p.get("estimated_price_range", ""),
                            "why_trending": p.get("why_trending", ""),
                            "source_article_title": p.get("source_title", ""),
                            "source_article_url": p.get("source_url", ""),
                            "is_extracted": True,
                        })

                logger.info("tiktok_llm_batch_extraction",
                           batch=batch_start // batch_size + 1,
                           extracted=len(all_products))

            except Exception as e:
                logger.warning("tiktok_llm_extraction_batch_failed",
                             batch=batch_start // batch_size + 1, error=str(e))
                continue

            # Small delay between batches to avoid rate limiting
            await asyncio.sleep(1)

        logger.info("tiktok_llm_extraction_complete",
                    total_articles=len(articles),
                    total_products=len(all_products))
        return all_products

    async def run_daily_research_cycle(self) -> TikTokResearchCycleResult:
        """Run the daily TikTok Shop product discovery cycle."""
        cycle_id = self._generate_id("ttc")
        started_at = datetime.now(timezone.utc)
        config = await self._get_config()
        daily = config.get("daily", DEFAULT_CONFIG["daily"])
        max_results = daily.get("max_results_per_query", 10)
        errors = []

        logger.info("tiktok_shop_research_cycle_start", cycle_id=cycle_id)

        # Get existing product names to avoid duplicates
        existing_names = set()
        async with get_session() as session:
            result = await session.execute(
                select(TikTokProductModel.name)
            )
            for row in result.all():
                if row[0]:
                    existing_names.add(row[0].lower().strip())

        # Search for products
        searxng = get_searxng_service()
        all_results = []

        for query in _get_search_queries():
            try:
                results = await searxng.search(query, num_results=max_results)
                all_results.extend(results)
            except Exception as e:
                errors.append(f"Search failed for '{query}': {e}")

        # Also search per niche
        for niche in DEFAULT_NICHES:
            try:
                results = await searxng.search(
                    f"tiktok shop {niche} products trending 2026",
                    num_results=5,
                )
                all_results.extend(results)
            except Exception as e:
                errors.append(f"Niche search failed for '{niche}': {e}")

        # Dedup articles by URL
        seen_urls = set()
        unique_results = []
        for r in all_results:
            url = r.url.lower() if hasattr(r, "url") else ""
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_results.append(r)

        logger.info("tiktok_shop_search_complete",
                     total=len(all_results), unique=len(unique_results))

        # Extract actual products from articles via LLM
        extracted_products = await self._extract_products_from_articles(unique_results)

        # Score and store products
        products_discovered = 0
        high_opportunity = []

        for product_data in extracted_products:
            try:
                name = product_data["name"]
                name_lower = name.lower().strip()

                # Skip if exact name duplicate
                if name_lower in existing_names:
                    continue

                # Fuzzy dedup: skip if very similar to existing name
                if self._is_fuzzy_duplicate(name_lower, existing_names):
                    logger.debug("tiktok_fuzzy_dedup_skip", name=name)
                    continue

                # Heuristic scoring
                score_text = name + " " + product_data.get("why_trending", "") + " " + product_data.get("category", "")
                scores = self._heuristic_score(name, score_text, "")

                # Detect niche from extraction data
                niche = product_data.get("category", "general")
                if niche == "general":
                    niche = self._detect_niche(name + " " + product_data.get("why_trending", ""))
                product_type = self._detect_product_type(name + " " + product_data.get("why_trending", ""))

                product_id = self._generate_id()
                opp_score = scores["opportunity_score"]
                initial_status = (
                    "pending_approval"
                    if opp_score >= daily.get("high_opportunity_threshold", 70)
                    else "discovered"
                )
                async with get_session() as session:
                    row = TikTokProductModel(
                        id=product_id,
                        name=name,
                        category="tiktok_shop",
                        niche=niche,
                        description=product_data.get("why_trending", ""),
                        source_url=product_data.get("source_article_url", ""),
                        product_type=product_type,
                        trend_score=scores["trend_score"],
                        competition_score=scores["competition_score"],
                        margin_score=scores["margin_score"],
                        opportunity_score=opp_score,
                        tags=scores.get("tags", []),
                        status=initial_status,
                        source_article_title=product_data.get("source_article_title", ""),
                        source_article_url=product_data.get("source_article_url", ""),
                        is_extracted=product_data.get("is_extracted", False),
                        why_trending=product_data.get("why_trending", ""),
                        estimated_price_range=product_data.get("estimated_price_range", ""),
                    )
                    session.add(row)

                products_discovered += 1
                existing_names.add(name.lower().strip())

                if opp_score >= daily.get("high_opportunity_threshold", 70):
                    high_opportunity.append({
                        "id": product_id,
                        "name": name,
                        "score": opp_score,
                        "niche": niche,
                    })

            except Exception as e:
                errors.append(f"Failed to process product: {e}")

        # LLM analysis for high scorers
        llm_analyzed = 0
        for product_data in high_opportunity[:10]:
            try:
                await self._llm_analyze_product(product_data["id"])
                llm_analyzed += 1
            except Exception as e:
                errors.append(f"LLM analysis failed: {e}")

        # Enrich high-opportunity products: images + success rating
        for product_data in high_opportunity[:10]:
            try:
                await self._fetch_product_image(
                    product_data["id"], product_data["name"],
                    product_data.get("niche", "general")
                )
                await self._calculate_success_rating(product_data["id"])
                await asyncio.sleep(0.5)
            except Exception as e:
                errors.append(f"Enrichment failed for {product_data['name']}: {e}")

        # Auto-approve products scoring >= 85 (high confidence)
        auto_approved = 0
        try:
            auto_approved = await self.auto_approve_high_confidence()
        except Exception as e:
            errors.append(f"Auto-approve failed: {e}")

        # Auto-create content topics for high-opportunity products
        content_topics_created = 0
        try:
            content_topics_created = await self._auto_create_content_topics(high_opportunity)
        except Exception as e:
            errors.append(f"Auto-create content topics failed: {e}")

        # Auto-create Legion tasks
        tasks_created = 0
        try:
            tasks_created = await self._auto_create_legion_tasks(
                high_opportunity[:daily.get("max_auto_tasks_per_cycle", 3)]
            )
        except Exception as e:
            errors.append(f"Auto-create Legion tasks failed: {e}")

        completed_at = datetime.now(timezone.utc)

        logger.info("tiktok_shop_research_cycle_complete",
                     cycle_id=cycle_id,
                     products=products_discovered,
                     high_opp=len(high_opportunity),
                     tasks=tasks_created,
                     errors=len(errors))

        # Notify
        try:
            from app.services.notification_service import get_notification_service
            ns = get_notification_service()
            await ns.create_notification(
                title="TikTok Shop Research Complete",
                message=(
                    f"Discovered {products_discovered} products, "
                    f"{len(high_opportunity)} high-opportunity, "
                    f"{tasks_created} Legion tasks created"
                ),
                channel="ui",
                source="tiktok_shop",
            )
        except Exception:
            pass

        return TikTokResearchCycleResult(
            cycle_id=cycle_id,
            started_at=started_at,
            completed_at=completed_at,
            products_discovered=products_discovered,
            products_researched=len(unique_results),
            high_opportunity_count=len(high_opportunity),
            content_topics_created=content_topics_created,
            tasks_created=tasks_created,
            errors=errors,
        )

    async def add_and_research_product(self, data: TikTokProductCreate) -> TikTokProduct:
        """Create a product manually and immediately run full research pipeline.

        Steps: create → SearXNG research → LLM analysis → images → sourcing → success rating.
        Returns the fully enriched product ready for approval.
        """
        product = await self.create_product(data)
        logger.info("tiktok_manual_add_start", product_id=product.id, name=data.name)

        try:
            researched = await self.research_product_deep(product.id)
            if researched:
                logger.info("tiktok_manual_add_complete", product_id=product.id, name=data.name)
                return researched
        except Exception as e:
            logger.error("tiktok_manual_add_research_failed", product_id=product.id, error=str(e))

        # Return partial product if research failed
        return await self.get_product(product.id) or product

    async def research_product_deep(self, product_id: str) -> Optional[TikTokProduct]:
        """Deep research a single product: competitor analysis, pricing, content angles."""
        product = await self.get_product(product_id)
        if not product:
            return None

        searxng = get_searxng_service()
        research_data = await searxng.research_topic(
            product.name,
            aspects=["competitor pricing", "profit margin", "supplier source",
                     "tiktok content angles", "customer reviews"],
        )

        # LLM analysis
        await self._llm_analyze_product(product_id, extra_context=research_data)

        # Enrich with image, sourcing info, success rating, and market data
        await self._fetch_product_image(product_id, product.name)
        await self._generate_sourcing_info(product_id)
        await self._calculate_success_rating(product_id)
        await self._estimate_market_data(product_id)

        # Update status
        await self.update_product(product_id, TikTokProductUpdate(
            status=TikTokProductStatus.RESEARCHED
        ))

        return await self.get_product(product_id)

    async def generate_content_ideas(
        self, product_id: str, count: int = 5
    ) -> List[Dict[str, Any]]:
        """Use LLM to generate content ideas for a product."""
        product = await self.get_product(product_id)
        if not product:
            return []

        try:
            from app.infrastructure.unified_llm_client import get_unified_llm_client

            client = get_unified_llm_client()

            prompt = (
                f"Generate {count} TikTok content ideas for selling this product:\n"
                f"Product: {product.name}\n"
                f"Niche: {product.niche or 'general'}\n"
                f"Type: {product.product_type}\n"
                f"Description: {(product.description or '')[:500]}\n\n"
                f"For each idea, provide:\n"
                f"1. Hook (first 3 seconds to grab attention)\n"
                f"2. Script outline (30-60 seconds)\n"
                f"3. Caption with hashtags\n"
                f"4. Content style (educational/review/trending/challenge)"
            )

            ideas = await self._retry_structured_chat(
                client,
                prompt=prompt,
                system="You are a TikTok content strategist.",
                task_type="structured_output",
                temperature=0.7,
                max_tokens=4096,
                output_schema=[{"hook": "str", "script": "str", "caption": "str", "style": "str"}],
            )

            if isinstance(ideas, list):
                async with get_session() as session:
                    db_result = await session.execute(
                        select(TikTokProductModel).where(
                            TikTokProductModel.id == product_id
                        )
                    )
                    row = db_result.scalar_one_or_none()
                    if row:
                        row.content_ideas = ideas
                return ideas

        except Exception as e:
            logger.error("tiktok_generate_ideas_failed", error=str(e))

        return []

    # ============================================
    # SCORING
    # ============================================

    def _heuristic_score(self, title: str, snippet: str, url: str) -> Dict[str, Any]:
        """Layer 1: Heuristic scoring for TikTok Shop products."""
        text = (title + " " + snippet).lower()
        tags = []

        # Trend score
        trend_base = 45
        for signal in TREND_SIGNALS:
            if signal in text:
                trend_base += 5
                tags.append(signal)
        trend_score = min(95, trend_base)

        # Competition score (higher = LESS competition = better)
        comp_base = 65  # assume moderate competition by default
        for signal in COMPETITION_SIGNALS:
            if signal in text:
                comp_base -= 10
        competition_score = max(10, min(95, comp_base))

        # Margin score
        margin_base = 45
        for signal in MARGIN_SIGNALS:
            if signal in text:
                margin_base += 5
                tags.append(signal)
        if "commission" in text or "affiliate" in text:
            margin_base += 8
        margin_score = min(95, margin_base)

        # Actionability
        action_base = 40
        for signal in ACTIONABILITY_SIGNALS:
            if signal in text:
                action_base += 4
        actionability = min(95, action_base)

        # Seasonal boost
        current_month = datetime.now().month
        seasonal_keywords = SEASONAL_MAP.get(current_month, [])
        seasonal_boost = 0
        for kw in seasonal_keywords:
            if kw in text:
                seasonal_boost += 3
        seasonal_boost = min(15, seasonal_boost)
        if seasonal_boost > 0:
            tags.append("seasonal")

        # Composite
        weights = DEFAULT_CONFIG["scoring_weights"]
        opportunity_score = (
            trend_score * weights["trend"]
            + competition_score * weights["inverse_competition"]
            + margin_score * weights["margin"]
            + actionability * weights["actionability"]
        ) + seasonal_boost

        return {
            "trend_score": round(trend_score, 1),
            "competition_score": round(competition_score, 1),
            "margin_score": round(margin_score, 1),
            "opportunity_score": round(max(0, min(100, opportunity_score)), 1),
            "tags": list(set(tags)),
        }

    async def _llm_analyze_product(
        self, product_id: str, extra_context: Optional[Dict] = None
    ) -> None:
        """Layer 2: LLM market analysis for a product."""
        async with get_session() as session:
            result = await session.execute(
                select(TikTokProductModel).where(TikTokProductModel.id == product_id)
            )
            row = result.scalar_one_or_none()
            if not row:
                return

            try:
                from app.infrastructure.unified_llm_client import get_unified_llm_client

                client = get_unified_llm_client()

                context = ""
                if extra_context and isinstance(extra_context, dict):
                    from app.services.searxng_service import get_searxng_service
                    sxng = get_searxng_service()
                    context = sxng.format_research_for_llm(extra_context)

                prompt = (
                    f"Analyze this TikTok Shop product opportunity:\n"
                    f"Name: {row.name}\n"
                    f"Description: {(row.description or '')[:500]}\n"
                    f"Source: {row.source_url or 'N/A'}\n"
                    f"{context}\n\n"
                    f"Provide a brief JSON analysis with:\n"
                    f"- summary: 2-3 sentence market viability assessment\n"
                    f"- trend_adj: adjustment to trend score (-10 to +10)\n"
                    f"- margin_adj: adjustment to margin score (-10 to +10)\n"
                    f"- suggested_niche: primary niche category\n"
                    f"- product_type: 'affiliate', 'dropship', or 'own'"
                )

                try:
                    analysis = await self._retry_structured_chat(
                        client,
                        prompt=prompt,
                        system="You are a TikTok Shop market analyst.",
                        task_type="extraction",
                        temperature=0.1,
                        max_tokens=2048,
                        output_schema={"summary": "str", "trend_adj": "int", "margin_adj": "int", "suggested_niche": "str", "product_type": "str"},
                    )
                except Exception:
                    analysis = None

                if analysis and isinstance(analysis, dict):
                    import json
                    try:
                        row.llm_analysis = analysis.get("summary", str(analysis)[:500])
                        row.trend_score = max(0, min(100,
                            row.trend_score + analysis.get("trend_adj", 0)))
                        row.margin_score = max(0, min(100,
                            row.margin_score + analysis.get("margin_adj", 0)))
                        if analysis.get("suggested_niche"):
                            row.niche = analysis["suggested_niche"]
                        if analysis.get("product_type") in ("affiliate", "dropship", "own"):
                            row.product_type = analysis["product_type"]

                        # Recompute opportunity score
                        weights = DEFAULT_CONFIG["scoring_weights"]
                        row.opportunity_score = round(
                            row.trend_score * weights["trend"]
                            + row.competition_score * weights["inverse_competition"]
                            + row.margin_score * weights["margin"]
                            + 50 * weights["actionability"],  # keep actionability at midpoint
                            1,
                        )
                        row.last_researched_at = datetime.now(timezone.utc)
                    except (KeyError, TypeError):
                        row.llm_analysis = str(analysis)[:500]

            except Exception as e:
                logger.warning("tiktok_llm_analysis_failed", product_id=product_id, error=str(e))

    async def _estimate_market_data(self, product_id: str) -> None:
        """Estimate monthly sales, competitor count, and commission rate via SearXNG + LLM."""
        async with get_session() as session:
            result = await session.execute(
                select(TikTokProductModel).where(TikTokProductModel.id == product_id)
            )
            row = result.scalar_one_or_none()
            if not row:
                return
            # Skip if already populated
            if row.estimated_monthly_sales and row.competitor_count and row.commission_rate:
                return

            try:
                searxng = get_searxng_service()
                search_results = await searxng.search(
                    f"{row.name} monthly sales volume tiktok shop sellers", num_results=5
                )
                snippets = ""
                if search_results:
                    snippets = " ".join(
                        getattr(r, "snippet", getattr(r, "content", ""))[:200]
                        for r in search_results[:5]
                    )

                from app.infrastructure.json_utils import extract_json_from_text, sanitize_for_prompt
                llm = get_zero_chat_model(task_type="extraction", temperature=0.2)
                safe_name = sanitize_for_prompt(row.name, max_length=200)
                safe_snippets = sanitize_for_prompt(snippets, max_length=1500)

                prompt = (
                    f"Estimate market data for this TikTok Shop product based on search results.\n\n"
                    f"Product: {safe_name}\n"
                    f"Niche: {row.niche or 'general'}\n"
                    f"Price range: ${row.price_range_min or '?'} - ${row.price_range_max or '?'}\n"
                    f"Search context: {safe_snippets}\n\n"
                    f"Return ONLY JSON:\n"
                    f'{{"estimated_monthly_sales": <int units sold per month, estimate 100-50000>,'
                    f' "competitor_count": <int number of sellers, estimate 1-500>,'
                    f' "commission_rate": <float percentage 0.01-0.30>}}'
                )
                response = await llm.ainvoke(prompt)
                text = response.content if hasattr(response, "content") else str(response)
                data = extract_json_from_text(text)

                if data and isinstance(data, dict):
                    if not row.estimated_monthly_sales:
                        val = data.get("estimated_monthly_sales")
                        if isinstance(val, (int, float)) and 0 < val < 1000000:
                            row.estimated_monthly_sales = int(val)
                    if not row.competitor_count:
                        val = data.get("competitor_count")
                        if isinstance(val, (int, float)) and 0 < val < 10000:
                            row.competitor_count = int(val)
                    if not row.commission_rate:
                        val = data.get("commission_rate")
                        if isinstance(val, (int, float)) and 0 < val <= 1.0:
                            row.commission_rate = float(val)
                    await session.flush()
                    logger.info("market_data_estimated", product_id=product_id,
                                sales=row.estimated_monthly_sales, competitors=row.competitor_count,
                                commission=row.commission_rate)

            except Exception as e:
                logger.warning("market_data_estimation_failed", product_id=product_id, error=str(e))

    async def update_score_from_performance(self, product_id: str) -> None:
        """Update product opportunity score based on content performance data."""
        from app.db.models import ContentPerformanceModel
        async with get_session() as session:
            # Get product
            prod_result = await session.execute(
                select(TikTokProductModel).where(TikTokProductModel.id == product_id)
            )
            row = prod_result.scalar_one_or_none()
            if not row:
                return

            # Get content performance for this product
            perf_result = await session.execute(
                select(ContentPerformanceModel).where(
                    ContentPerformanceModel.tiktok_product_id == product_id
                )
            )
            perfs = perf_result.scalars().all()
            if not perfs:
                return

            # Calculate average performance score
            total_score = sum(p.performance_score for p in perfs)
            avg_score = total_score / len(perfs) if perfs else 0

            # Find best template type from video_scripts linked to high-performing content
            from app.db.models import VideoScriptModel
            best_template = None
            best_engagement = 0
            for p in perfs:
                if p.engagement_rate > best_engagement and p.topic_id:
                    best_engagement = p.engagement_rate
                    # Try to find script linked to this topic
                    script_result = await session.execute(
                        select(VideoScriptModel).where(
                            VideoScriptModel.product_id == product_id
                        ).order_by(VideoScriptModel.created_at.desc()).limit(1)
                    )
                    script = script_result.scalar_one_or_none()
                    if script:
                        best_template = script.template_type

            # Blend: 70% original score + 30% performance score (normalized to 0-100)
            perf_normalized = min(100, avg_score)
            blended = 0.7 * row.opportunity_score + 0.3 * perf_normalized
            row.opportunity_score = round(max(0, min(100, blended)), 1)
            row.content_performance_score = round(avg_score, 1)
            if best_template:
                row.best_template_type = best_template
            row.last_performance_update_at = datetime.now(timezone.utc)
            await session.flush()

            logger.info("performance_feedback_applied", product_id=product_id,
                        avg_perf=round(avg_score, 1), blended_score=row.opportunity_score,
                        best_template=best_template)

    async def get_best_template_for_niche(self, niche: str) -> Optional[str]:
        """Get the best-performing template type for a niche based on content performance data."""
        from app.db.models import VideoScriptModel, ContentPerformanceModel
        async with get_session() as session:
            # Get products in this niche
            prod_result = await session.execute(
                select(TikTokProductModel.id).where(TikTokProductModel.niche == niche)
            )
            product_ids = [r[0] for r in prod_result.all()]
            if not product_ids:
                return None

            # Get scripts for these products with performance data
            template_scores = {}
            for pid in product_ids:
                script_result = await session.execute(
                    select(VideoScriptModel).where(VideoScriptModel.product_id == pid)
                )
                scripts = script_result.scalars().all()
                for script in scripts:
                    perf_result = await session.execute(
                        select(ContentPerformanceModel).where(
                            ContentPerformanceModel.tiktok_product_id == pid
                        )
                    )
                    perfs = perf_result.scalars().all()
                    if perfs:
                        avg_eng = sum(p.engagement_rate for p in perfs) / len(perfs)
                        tt = script.template_type
                        if tt not in template_scores:
                            template_scores[tt] = []
                        template_scores[tt].append(avg_eng)

            if not template_scores:
                return None

            # Find template with highest average engagement
            best = max(template_scores, key=lambda t: sum(template_scores[t]) / len(template_scores[t]))
            return best

    async def get_template_analytics(self) -> List[Dict[str, Any]]:
        """Get template performance analytics across all niches."""
        from app.db.models import VideoScriptModel
        async with get_session() as session:
            # Count scripts by template type
            result = await session.execute(
                select(
                    VideoScriptModel.template_type,
                    sql_func.count(VideoScriptModel.id).label("count"),
                ).group_by(VideoScriptModel.template_type)
            )
            rows = result.all()

            analytics = []
            for template_type, count in rows:
                # Get average performance for products with this template
                script_result = await session.execute(
                    select(VideoScriptModel.product_id).where(
                        VideoScriptModel.template_type == template_type
                    ).distinct()
                )
                product_ids = [r[0] for r in script_result.all()]

                avg_perf = 0
                if product_ids:
                    perf_result = await session.execute(
                        select(TikTokProductModel.content_performance_score).where(
                            TikTokProductModel.id.in_(product_ids),
                            TikTokProductModel.content_performance_score.isnot(None),
                        )
                    )
                    scores = [r[0] for r in perf_result.all() if r[0] is not None]
                    avg_perf = sum(scores) / len(scores) if scores else 0

                analytics.append({
                    "template_type": template_type,
                    "script_count": count,
                    "product_count": len(product_ids),
                    "avg_performance_score": round(avg_perf, 1),
                })

            return sorted(analytics, key=lambda x: x["avg_performance_score"], reverse=True)

    # ============================================
    # AUTO-INTEGRATION
    # ============================================

    async def _auto_create_content_topics(
        self, high_opportunity: List[Dict]
    ) -> int:
        """Create ContentTopic records for high-opportunity products."""
        created = 0
        try:
            from app.services.content_agent_service import get_content_agent_service
            from app.models.content_agent import ContentTopicCreate
            svc = get_content_agent_service()

            for product_data in high_opportunity[:5]:
                # Check if topic already exists for this product
                existing = await svc.list_topics()
                already_exists = any(
                    t.tiktok_product_id == product_data["id"] for t in existing
                )
                if already_exists:
                    continue

                topic = await svc.create_topic(ContentTopicCreate(
                    name=f"TikTok: {product_data['name'][:150]}",
                    description=f"Content for TikTok Shop product: {product_data['name']}",
                    niche=product_data.get("niche", "general"),
                    platform="tiktok",
                    tiktok_product_id=product_data["id"],
                ))

                # Link back
                async with get_session() as session:
                    result = await session.execute(
                        select(TikTokProductModel).where(
                            TikTokProductModel.id == product_data["id"]
                        )
                    )
                    row = result.scalar_one_or_none()
                    if row:
                        row.linked_content_topic_id = topic.id
                        row.status = "content_planned"

                created += 1

        except Exception as e:
            logger.error("tiktok_auto_create_topics_failed", error=str(e))

        return created

    async def _auto_create_legion_tasks(self, products: List[Dict]) -> int:
        """Create Legion tasks for high-opportunity products."""
        created = 0
        try:
            from app.services.legion_client import get_legion_client
            legion = get_legion_client()

            if not await legion.health_check():
                logger.warning("legion_unavailable_for_tiktok_tasks")
                return 0

            sprint = await self._get_or_create_tiktok_sprint(legion)
            if not sprint:
                return 0

            sprint_id = sprint.get("id")
            for product_data in products:
                try:
                    task = await legion.create_task(sprint_id, {
                        "title": f"[TikTok Shop] Research & list: {product_data['name'][:200]}",
                        "description": (
                            f"Opportunity score: {product_data.get('score', 0):.0f}/100\n"
                            f"Niche: {product_data.get('niche', 'unknown')}\n"
                            f"Action: Research suppliers, evaluate margins, create listing"
                        ),
                        "prompt": (
                            f"Research the TikTok Shop product '{product_data['name']}'. "
                            f"Find suppliers, evaluate profit margins, and create a product listing. "
                            f"Niche: {product_data.get('niche', 'general')}."
                        ),
                        "priority": 3,
                    })
                    if task:
                        # Link task back to product
                        async with get_session() as session:
                            result = await session.execute(
                                select(TikTokProductModel).where(
                                    TikTokProductModel.id == product_data["id"]
                                )
                            )
                            row = result.scalar_one_or_none()
                            if row and task.get("id"):
                                row.linked_legion_task_id = str(task["id"])
                        created += 1
                except Exception as e:
                    logger.warning("tiktok_task_creation_failed", error=str(e))

        except Exception as e:
            logger.error("tiktok_auto_create_tasks_failed", error=str(e))

        return created

    async def _get_or_create_tiktok_sprint(self, legion) -> Optional[Dict]:
        """Find or create a TikTok Shop sprint in Legion."""
        try:
            sprints = await legion.list_sprints()
            if isinstance(sprints, list):
                for s in sprints:
                    if "tiktok" in s.get("name", "").lower() and s.get("status") in ("active", "planned"):
                        return s

            # Create new sprint
            today = datetime.now().strftime("%Y-%m-%d")
            new_sprint = await legion.create_sprint({
                "project_id": ZERO_PROJECT_ID,
                "name": f"TikTok Shop Research - {today}",
                "status": "planned",
            })
            return new_sprint
        except Exception as e:
            logger.error("tiktok_sprint_creation_failed", error=str(e))
            return None

    # ============================================
    # HELPERS
    # ============================================

    @staticmethod
    def _is_fuzzy_duplicate(name: str, existing_names: set, threshold: float = 0.85) -> bool:
        """Check if a product name is too similar to any existing name (fuzzy match)."""
        from difflib import SequenceMatcher

        name_lower = name.lower().strip()
        name_words = set(name_lower.split())
        if not name_words:
            return False
        for existing in existing_names:
            existing_lower = existing.lower().strip()
            existing_words = set(existing_lower.split())
            if not existing_words:
                continue
            # Jaccard similarity on words
            intersection = name_words & existing_words
            union = name_words | existing_words
            similarity = len(intersection) / len(union) if union else 0
            if similarity >= threshold:
                return True
            # Substring check (case-insensitive)
            if name_lower in existing_lower or existing_lower in name_lower:
                return True
            # Character-level similarity for close matches (catches "LED Lights" vs "LED Lights Pro")
            ratio = SequenceMatcher(None, name_lower, existing_lower).ratio()
            if ratio >= 0.82:
                return True
        return False

    def _detect_niche(self, text: str) -> str:
        text_lower = text.lower()
        for niche in DEFAULT_NICHES:
            if niche in text_lower:
                return niche
        return "general"

    def _detect_product_type(self, text: str) -> str:
        text_lower = text.lower()
        if "affiliate" in text_lower or "commission" in text_lower:
            return "affiliate"
        if "dropship" in text_lower or "dropshipping" in text_lower:
            return "dropship"
        return "unknown"

    def _model_to_pydantic(self, row: TikTokProductModel) -> TikTokProduct:
        return TikTokProduct(
            id=row.id,
            name=row.name,
            category=row.category or "general",
            niche=row.niche,
            description=row.description,
            source_url=row.source_url,
            source_engine=row.source_engine,
            marketplace_url=row.marketplace_url,
            product_type=row.product_type or "unknown",
            trend_score=row.trend_score or 50.0,
            competition_score=row.competition_score or 50.0,
            margin_score=row.margin_score or 50.0,
            opportunity_score=row.opportunity_score or 50.0,
            price_range_min=row.price_range_min,
            price_range_max=row.price_range_max,
            estimated_monthly_sales=row.estimated_monthly_sales,
            competitor_count=row.competitor_count,
            commission_rate=row.commission_rate,
            tags=row.tags or [],
            llm_analysis=row.llm_analysis,
            content_ideas=row.content_ideas or [],
            status=row.status or "discovered",
            linked_content_topic_id=row.linked_content_topic_id,
            linked_legion_task_id=row.linked_legion_task_id,
            approved_at=row.approved_at,
            rejected_at=row.rejected_at,
            rejection_reason=row.rejection_reason,
            source_article_title=row.source_article_title,
            source_article_url=row.source_article_url,
            is_extracted=row.is_extracted if row.is_extracted is not None else False,
            why_trending=row.why_trending,
            estimated_price_range=row.estimated_price_range,
            image_url=row.image_url,
            image_urls=row.image_urls or [],
            image_validated=row.image_validated if hasattr(row, 'image_validated') and row.image_validated else False,
            success_rating=row.success_rating,
            success_factors=row.success_factors or {},
            supplier_url=row.supplier_url,
            supplier_name=row.supplier_name,
            sourcing_method=row.sourcing_method,
            sourcing_notes=row.sourcing_notes,
            sourcing_links=row.sourcing_links or [],
            listing_steps=row.listing_steps or [],
            affiliate_link=getattr(row, "affiliate_link", None),
            tiktok_shop_url=getattr(row, "tiktok_shop_url", None),
            import_url=getattr(row, "import_url", None),
            import_source=getattr(row, "import_source", None),
            discovered_at=row.discovered_at or datetime.now(timezone.utc),
            last_researched_at=row.last_researched_at,
        )

    # ============================================
    # ENRICHMENT: Images, Success Rating, Sourcing
    # ============================================

    async def _validate_image_url(self, url: str) -> bool:
        """HTTP HEAD check if a URL points to a valid image."""
        import aiohttp
        try:
            async with aiohttp.ClientSession() as http:
                async with http.head(url, timeout=aiohttp.ClientTimeout(total=5), allow_redirects=True) as resp:
                    if resp.status != 200:
                        return False
                    ct = resp.headers.get("content-type", "")
                    return ct.startswith("image/")
        except Exception:
            return False

    async def _fetch_product_image(self, product_id: str, product_name: str, niche: str = "general") -> Optional[str]:
        """Multi-source image search with HTTP HEAD validation."""
        searxng = get_searxng_service()

        # Multiple query strategies for better coverage
        queries = [
            (f"{product_name} product photo", "images"),
            (f"{product_name} {niche} product", "images"),
            (f"{product_name} amazon listing", "images"),
            (f"{product_name} aliexpress", "images"),
            (f"{product_name} product", "general"),  # Fallback to web search for image URLs
        ]

        all_candidate_urls = []

        for query_text, category in queries:
            try:
                cats = [category] if category != "general" else None
                results = await searxng.search(query_text, num_results=8, categories=cats)

                if category == "images":
                    urls = [r.img_src for r in results if r.img_src]
                else:
                    urls = [
                        r.url for r in results
                        if r.url and any(ext in r.url.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"])
                    ]

                all_candidate_urls.extend(urls)
                await asyncio.sleep(0.5)  # Rate limit
            except Exception as e:
                logger.debug("tiktok_image_search_error", query=query_text, error=str(e))

        # Deduplicate
        seen = set()
        unique_urls = []
        for u in all_candidate_urls:
            if u not in seen:
                seen.add(u)
                unique_urls.append(u)

        # Validate each URL via HTTP HEAD (up to 15 candidates)
        validated_urls = []
        for url in unique_urls[:15]:
            if await self._validate_image_url(url):
                validated_urls.append(url)
                if len(validated_urls) >= 5:
                    break

        # Store results
        async with get_session() as session:
            result = await session.execute(
                select(TikTokProductModel).where(TikTokProductModel.id == product_id)
            )
            row = result.scalar_one_or_none()
            if row:
                if validated_urls:
                    row.image_url = validated_urls[0]
                    row.image_urls = validated_urls[:5]
                    row.image_validated = True
                row.image_search_done = True

        if validated_urls:
            logger.info("tiktok_image_fetched", product_id=product_id, count=len(validated_urls), validated=True)
            return validated_urls[0]

        logger.debug("tiktok_image_none_valid", product_id=product_id, candidates=len(unique_urls))
        return None

    async def backfill_images(self, limit: int = 20) -> int:
        """Fetch images for products that don't have validated images yet."""
        async with get_session() as session:
            result = await session.execute(
                select(TikTokProductModel).where(
                    TikTokProductModel.image_validated == False,
                    TikTokProductModel.status.in_(["approved", "active", "content_planned", "pending_approval"]),
                ).order_by(TikTokProductModel.opportunity_score.desc()).limit(limit)
            )
            rows = result.scalars().all()
            products = [(r.id, r.name, r.niche or "general") for r in rows]

        fetched = 0
        for pid, name, niche in products:
            try:
                url = await self._fetch_product_image(pid, name, niche)
                if url:
                    fetched += 1
                await asyncio.sleep(1)  # Rate limit SearXNG
            except Exception:
                pass
        logger.info("tiktok_image_backfill_complete", fetched=fetched, total=len(products))
        return fetched

    async def revalidate_images(self, limit: int = 20) -> int:
        """Re-check existing image URLs and re-search if dead."""
        async with get_session() as session:
            result = await session.execute(
                select(TikTokProductModel).where(
                    TikTokProductModel.image_validated == False,
                    TikTokProductModel.image_url.isnot(None),
                    TikTokProductModel.status.notin_(["rejected"]),
                ).order_by(TikTokProductModel.opportunity_score.desc()).limit(limit)
            )
            rows = result.scalars().all()
            products = [(r.id, r.name, r.niche or "general", r.image_url) for r in rows]

        fixed = 0
        for pid, name, niche, current_url in products:
            try:
                # Check if current URL is still valid
                if current_url and await self._validate_image_url(current_url):
                    async with get_session() as session:
                        result = await session.execute(
                            select(TikTokProductModel).where(TikTokProductModel.id == pid)
                        )
                        row = result.scalar_one_or_none()
                        if row:
                            row.image_validated = True
                    fixed += 1
                else:
                    # URL is dead, re-search
                    url = await self._fetch_product_image(pid, name, niche)
                    if url:
                        fixed += 1
                await asyncio.sleep(1)
            except Exception:
                pass
        logger.info("tiktok_image_revalidation_complete", fixed=fixed, total=len(products))
        return fixed

    async def _calculate_success_rating(self, product_id: str) -> Optional[float]:
        """Calculate a 1-100 success rating for selling this product.

        Factors: trend, competition, margin, content viability, supply chain, price point.
        """
        product = await self.get_product(product_id)
        if not product:
            return None

        # Existing scores
        trend = product.trend_score
        competition = product.competition_score
        margin = product.margin_score

        # Content viability: products with visual appeal, demo-ability
        content_viability = 50.0
        text = ((product.name or "") + " " + (product.description or "") + " " + (product.why_trending or "")).lower()
        content_signals = [
            "before after", "transformation", "satisfying", "asmr",
            "unboxing", "review", "demo", "tutorial", "hack", "diy",
            "skincare", "makeup", "glow", "clean", "organize",
        ]
        for signal in content_signals:
            if signal in text:
                content_viability += 7
        content_viability = min(95, content_viability)

        # Supply chain score
        supply_map = {"affiliate": 85.0, "dropship": 65.0, "own": 45.0, "unknown": 50.0}
        supply_chain = supply_map.get(product.product_type, 50.0)
        if product.supplier_url:
            supply_chain = min(95, supply_chain + 15)

        # Price point: TikTok impulse buy sweet spot $15-$50
        price_point = 50.0
        if product.price_range_min and product.price_range_max:
            avg_price = (product.price_range_min + product.price_range_max) / 2
            if 15 <= avg_price <= 50:
                price_point = 85.0
            elif 10 <= avg_price <= 80:
                price_point = 65.0
            elif avg_price > 100:
                price_point = 30.0
        elif product.estimated_price_range:
            # Parse "$15-$30" style
            import re
            nums = re.findall(r'\d+(?:\.\d+)?', product.estimated_price_range)
            if len(nums) >= 2:
                avg_price = (float(nums[0]) + float(nums[1])) / 2
                if 15 <= avg_price <= 50:
                    price_point = 85.0
                elif 10 <= avg_price <= 80:
                    price_point = 65.0
            elif len(nums) == 1:
                p = float(nums[0])
                if 15 <= p <= 50:
                    price_point = 80.0

        factors = {
            "trend": round(trend, 1),
            "competition": round(competition, 1),
            "margin": round(margin, 1),
            "content_viability": round(content_viability, 1),
            "supply_chain": round(supply_chain, 1),
            "price_point": round(price_point, 1),
        }

        weights = {
            "trend": 0.20,
            "competition": 0.15,
            "margin": 0.20,
            "content_viability": 0.15,
            "supply_chain": 0.15,
            "price_point": 0.15,
        }

        success_rating = sum(factors[k] * weights[k] for k in weights)
        success_rating = round(max(1, min(100, success_rating)), 1)

        async with get_session() as session:
            result = await session.execute(
                select(TikTokProductModel).where(TikTokProductModel.id == product_id)
            )
            row = result.scalar_one_or_none()
            if row:
                row.success_rating = success_rating
                row.success_factors = factors

        return success_rating

    async def _validate_url(self, url: str) -> Dict[str, Any]:
        """HTTP HEAD check a URL and classify it."""
        import aiohttp
        try:
            async with aiohttp.ClientSession() as http:
                async with http.head(url, timeout=aiohttp.ClientTimeout(total=8), allow_redirects=True) as resp:
                    final_url = str(resp.url)
                    is_valid = resp.status == 200

                    # Classify the link
                    link_class = "unknown"
                    url_lower = final_url.lower()
                    if not is_valid or resp.status == 404:
                        link_class = "dead"
                    elif "search" in url_lower or "query=" in url_lower or "s=" in url_lower:
                        link_class = "search_page"
                    elif any(p in url_lower for p in ["/item/", "/product/", "/dp/", "/listing/", "/i/"]):
                        link_class = "active_listing"
                    elif is_valid:
                        link_class = "active_listing"

                    return {
                        "status_code": resp.status,
                        "final_url": final_url,
                        "is_valid": is_valid,
                        "link_class": link_class,
                    }
        except Exception:
            return {"status_code": 0, "final_url": url, "is_valid": False, "link_class": "dead"}

    async def _generate_sourcing_info(self, product_id: str) -> None:
        """Use LLM + SearXNG to generate sourcing information with validated links."""
        product = await self.get_product(product_id)
        if not product:
            return

        searxng = get_searxng_service()

        # Multiple search queries for better supplier coverage
        search_queries = [
            f"{product.name} supplier wholesale dropship aliexpress",
            f"{product.name} buy online best price",
            f"{product.name} {product.niche or ''} aliexpress cjdropshipping",
        ]

        all_results = []
        for query in search_queries:
            try:
                results = await searxng.search(query, num_results=8)
                all_results.extend(results)
                await asyncio.sleep(0.5)
            except Exception:
                pass

        # Deduplicate by URL
        seen_urls = set()
        unique_results = []
        for r in all_results:
            if r.url not in seen_urls:
                seen_urls.add(r.url)
                unique_results.append(r)

        # Build and validate sourcing links
        sourcing_links = []
        for r in unique_results[:15]:
            url_lower = r.url.lower()
            link_type = "other"
            if "aliexpress" in url_lower:
                link_type = "aliexpress"
            elif "alibaba" in url_lower or "1688" in url_lower:
                link_type = "alibaba"
            elif "cjdropshipping" in url_lower or "cj.com" in url_lower:
                link_type = "cj_dropshipping"
            elif "amazon" in url_lower:
                link_type = "amazon"
            elif "tiktok" in url_lower and "shop" in url_lower:
                link_type = "tiktok_shop"

            # Validate the URL
            validation = await self._validate_url(r.url)

            sourcing_links.append({
                "name": r.title[:200],
                "url": validation.get("final_url", r.url),
                "type": link_type,
                "snippet": (r.snippet or "")[:200],
                "link_status": validation.get("link_class", "unknown"),
                "is_valid": validation.get("is_valid", False),
            })

        # Filter to only valid links for LLM
        valid_links = [l for l in sourcing_links if l["is_valid"]]
        active_listings = [l for l in valid_links if l["link_status"] == "active_listing"]

        # LLM-generated sourcing guide - only use validated URLs
        try:
            import json
            from app.infrastructure.unified_llm_client import get_unified_llm_client

            client = get_unified_llm_client()

            links_for_llm = active_listings or valid_links
            supplier_text = "\n".join(
                f"- {l['name'][:100]}: {l['url']}" for l in links_for_llm[:10]
            )

            prompt = (
                f"Generate a sourcing guide for selling '{product.name}' on TikTok Shop.\n"
                f"Product type: {product.product_type}\n"
                f"Niche: {product.niche or 'general'}\n"
                f"Price range: {product.estimated_price_range or 'Unknown'}\n\n"
                f"Validated supplier links found online:\n{supplier_text}\n\n"
                f"IMPORTANT: You MUST only use URLs from the list above. Do NOT invent URLs.\n"
                f"Provide:\n"
                f"- sourcing_method: one of 'aliexpress', 'cj_dropshipping', 'tiktok_affiliate', 'direct_wholesale', 'amazon_fba'\n"
                f"- supplier_name: recommended supplier name\n"
                f"- supplier_url: best supplier URL from the list above (must be a real URL from the list)\n"
                f"- sourcing_notes: 2-3 paragraph guide on how to source and list this product\n"
                f"- listing_steps: array of 5-8 step strings for listing on TikTok Shop"
            )

            result = await self._retry_structured_chat(
                client,
                prompt=prompt,
                system="You are a TikTok Shop sourcing expert. Only recommend URLs from the provided validated list.",
                task_type="extraction",
                temperature=0.2,
                max_tokens=4096,
                output_schema={"sourcing_method": "str", "supplier_name": "str", "supplier_url": "str", "sourcing_notes": "str", "listing_steps": ["str"]},
            )

            # Validate the LLM-suggested supplier_url against our validated list
            llm_url = result.get("supplier_url", "")
            valid_url_set = {l["url"] for l in valid_links}
            if llm_url and llm_url not in valid_url_set:
                # LLM hallucinated a URL - pick best from validated list instead
                if active_listings:
                    llm_url = active_listings[0]["url"]
                    result["supplier_name"] = active_listings[0]["name"]
                elif valid_links:
                    llm_url = valid_links[0]["url"]
                    result["supplier_name"] = valid_links[0]["name"]
                else:
                    llm_url = ""

            async with get_session() as session:
                db_result = await session.execute(
                    select(TikTokProductModel).where(TikTokProductModel.id == product_id)
                )
                row = db_result.scalar_one_or_none()
                if row:
                    row.sourcing_method = result.get("sourcing_method", "")[:50]
                    row.supplier_name = result.get("supplier_name", "")[:200]
                    row.supplier_url = llm_url
                    row.sourcing_notes = result.get("sourcing_notes", "")
                    row.listing_steps = result.get("listing_steps", [])
                    row.sourcing_links = sourcing_links[:10]

            logger.info("tiktok_sourcing_generated", product_id=product_id, valid_links=len(valid_links))

        except Exception as e:
            logger.warning("tiktok_sourcing_generation_failed", product_id=product_id, error=str(e))
            # Still save the sourcing links even if LLM fails
            async with get_session() as session:
                db_result = await session.execute(
                    select(TikTokProductModel).where(TikTokProductModel.id == product_id)
                )
                row = db_result.scalar_one_or_none()
                if row:
                    row.sourcing_links = sourcing_links[:10]

    async def enrich_product(self, product_id: str) -> Optional[TikTokProduct]:
        """Enrich a product with image, sourcing info, and success rating."""
        product = await self.get_product(product_id)
        if not product:
            return None

        # Fetch image if not validated or missing
        if not product.image_url or not product.image_validated:
            await self._fetch_product_image(product_id, product.name, product.niche or "general")

        # Generate sourcing info if missing
        if not product.sourcing_notes:
            await self._generate_sourcing_info(product_id)

        # Calculate success rating and estimate market data
        await self._calculate_success_rating(product_id)
        await self._estimate_market_data(product_id)

        return await self.get_product(product_id)

    async def cleanup_article_title_products(self) -> Dict[str, int]:
        """Clean up products that have article titles as names. Checks ALL non-rejected products."""
        async with get_session() as session:
            result = await session.execute(
                select(TikTokProductModel).where(
                    TikTokProductModel.status != "rejected"
                )
            )
            products = result.scalars().all()

        stats = {"rejected": 0, "kept": 0}
        article_patterns = [
            "top products", "best selling", "trending products",
            "tiktok made me", "here are the", "list of",
            "most popular", "you need to buy", "how to",
            "best products", "what products", "discover",
            "this week's", "guide", "tips for",
            "top selling", "top tiktok", "top 5 ", "top 8 ",
            "top 10 ", "top 15 ", "top 20 ", "top 50 ",
            "top 100", "top-selling",
            "rank your", "advanced seo", "categories that",
            "products to sell", "products for 2026",
            "products for 2025", "dropshipping", "dropship",
            "shopify", "printify", "r/dropshipping", "r/dropship",
            "r/analyzify", "r/ugc", ": r/",
            "50m€", "- shopify", ": advanced",
            "best-sellers leaderboard", "fastmoss",
            "sell the trend", "helium 10", "minea",
            "viral products", "viral gifts", "viral beauty",
            "made me buy it", "trending finds",
            "what's selling", "what actually works",
            "organic is brutal", "product challenge",
            "product search & filter", "skeptical of",
            "obsessed teen", "social commerce",
            "sellers behind", "oreate ai",
            "profitable products", "under-$", "from $",
            "best-selling products on amazon",
            "| tiktok", "tiktokmademebuyit",
        ]

        for product in products:
            name_lower = product.name.lower().strip()
            is_article = (
                len(product.name) > 80
                or any(p in name_lower for p in article_patterns)
                or name_lower.startswith("trending ")
                or name_lower.startswith("best ")
                or name_lower.startswith("top ")
                or name_lower.startswith("find ")
                or name_lower.endswith("| tiktok")
                or "?" in product.name
            )

            if is_article:
                async with get_session() as session:
                    result = await session.execute(
                        select(TikTokProductModel).where(TikTokProductModel.id == product.id)
                    )
                    row = result.scalar_one_or_none()
                    if row:
                        row.status = "rejected"
                        row.rejection_reason = "Auto-cleaned: article title, not a real product"
                stats["rejected"] += 1
            else:
                stats["kept"] += 1

        logger.info("tiktok_cleanup_complete", **stats)
        return stats

    # ============================================
    # STATS
    # ============================================

    async def get_stats(self) -> TikTokShopStats:
        async with get_session() as session:
            total = await session.execute(
                select(sql_func.count()).select_from(TikTokProductModel)
            )
            active = await session.execute(
                select(sql_func.count()).select_from(TikTokProductModel).where(
                    TikTokProductModel.status == "active"
                )
            )
            discovered = await session.execute(
                select(sql_func.count()).select_from(TikTokProductModel).where(
                    TikTokProductModel.status == "discovered"
                )
            )
            pending = await session.execute(
                select(sql_func.count()).select_from(TikTokProductModel).where(
                    TikTokProductModel.status == "pending_approval"
                )
            )
            approved = await session.execute(
                select(sql_func.count()).select_from(TikTokProductModel).where(
                    TikTokProductModel.status == "approved"
                )
            )
            avg_score = await session.execute(
                select(sql_func.avg(TikTokProductModel.opportunity_score))
            )
            week_ago = datetime.now(timezone.utc) - timedelta(days=7)
            this_week = await session.execute(
                select(sql_func.count()).select_from(TikTokProductModel).where(
                    TikTokProductModel.discovered_at >= week_ago
                )
            )
            linked = await session.execute(
                select(sql_func.count()).select_from(TikTokProductModel).where(
                    TikTokProductModel.linked_content_topic_id.isnot(None)
                )
            )

            # Top niches
            niche_result = await session.execute(
                select(TikTokProductModel.niche, sql_func.count().label("cnt"))
                .where(TikTokProductModel.niche.isnot(None))
                .group_by(TikTokProductModel.niche)
                .order_by(sql_func.count().desc())
                .limit(5)
            )
            top_niches = [r[0] for r in niche_result.all() if r[0]]

            # Last research
            last = await session.execute(
                select(sql_func.max(TikTokProductModel.last_researched_at))
            )

            return TikTokShopStats(
                total_products=total.scalar() or 0,
                active_products=active.scalar() or 0,
                discovered_products=discovered.scalar() or 0,
                pending_approval_products=pending.scalar() or 0,
                approved_products=approved.scalar() or 0,
                avg_opportunity_score=round(avg_score.scalar() or 0, 1),
                top_niches=top_niches,
                products_this_week=this_week.scalar() or 0,
                content_topics_linked=linked.scalar() or 0,
                last_research_at=last.scalar(),
            )


    async def seed_e2e_test(self, count: int = 5) -> Dict[str, Any]:
        """Run full E2E test: research → pick top products → approve → generate scripts → queue for review.

        Returns summary of what was created.
        """
        from app.services.tiktok_video_service import get_tiktok_video_service
        from app.models.tiktok_content import VideoTemplateType

        templates = list(VideoTemplateType)
        video_svc = get_tiktok_video_service()
        errors = []

        # Step 1: Run live research cycle
        logger.info("e2e_seed_starting_research")
        try:
            cycle_result = await self.run_daily_research_cycle()
        except Exception as e:
            logger.error("e2e_seed_research_failed", error=str(e))
            errors.append(f"Research cycle failed: {str(e)}")
            cycle_result = None

        # Step 2: Get top products by opportunity score (any status)
        async with get_session() as session:
            result = await session.execute(
                select(TikTokProductModel)
                .where(TikTokProductModel.status.in_([
                    "discovered", "pending_approval", "approved", "researched"
                ]))
                .order_by(TikTokProductModel.opportunity_score.desc())
                .limit(count)
            )
            top_products = result.scalars().all()

        if len(top_products) == 0:
            return {
                "success": False,
                "error": "No products found. Research cycle may have failed or SearXNG is unavailable.",
                "errors": errors,
            }

        # Step 3: Approve them
        product_ids = [p.id for p in top_products]
        approved_count = await self.batch_approve(product_ids)

        # Step 4: Generate video scripts — one per template type (cycle if more products than templates)
        scripts_created = []
        for i, product in enumerate(top_products):
            template = templates[i % len(templates)]
            try:
                script = await video_svc.generate_video_script(
                    product_id=product.id,
                    template_type=template,
                )
                if script:
                    scripts_created.append({
                        "script_id": script.id,
                        "product_name": product.name,
                        "template": template.value,
                    })
            except Exception as e:
                logger.warning("e2e_seed_script_failed", product=product.name, error=str(e))
                errors.append(f"Script generation failed for {product.name}: {str(e)}")

        # Step 5: Queue each script for generation and set publish_status=pending_review
        queue_items = []
        for sc in scripts_created:
            try:
                queue_item = await video_svc.queue_for_generation(sc["script_id"])
                if queue_item:
                    # Set publish_status to pending_review and pre-fill caption
                    async with get_session() as session:
                        from app.db.models import ContentQueueModel, VideoScriptModel
                        q_result = await session.execute(
                            select(ContentQueueModel).where(ContentQueueModel.id == queue_item.id)
                        )
                        q_row = q_result.scalar_one_or_none()
                        if q_row:
                            q_row.publish_status = "pending_review"
                            # Pre-fill caption from script's CTA + product name
                            s_result = await session.execute(
                                select(VideoScriptModel).where(VideoScriptModel.id == sc["script_id"])
                            )
                            s_row = s_result.scalar_one_or_none()
                            if s_row:
                                q_row.caption = s_row.cta_text or f"Check out this amazing product!"
                                q_row.hashtags = ["fyp", "tiktokshop", "trending", "musthave", "viral"]
                            await session.flush()

                    queue_items.append(queue_item.id)
            except Exception as e:
                logger.warning("e2e_seed_queue_failed", script=sc["script_id"], error=str(e))
                errors.append(f"Queue failed for script {sc['script_id']}: {str(e)}")

        logger.info(
            "e2e_seed_complete",
            products=len(top_products),
            scripts=len(scripts_created),
            queued=len(queue_items),
        )

        return {
            "success": True,
            "products_found": len(top_products),
            "products_approved": approved_count,
            "scripts_generated": len(scripts_created),
            "items_queued_for_review": len(queue_items),
            "scripts": scripts_created,
            "queue_ids": queue_items,
            "errors": errors,
            "research_cycle": {
                "products_discovered": cycle_result.products_discovered if cycle_result else 0,
                "high_opportunity": cycle_result.high_opportunity_count if cycle_result else 0,
            } if cycle_result else None,
        }


@lru_cache()
def get_tiktok_shop_service() -> TikTokShopService:
    """Get cached TikTok Shop service instance."""
    return TikTokShopService()
