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
from app.infrastructure.langchain_adapter import get_zero_chat_model

logger = structlog.get_logger()

ZERO_PROJECT_ID = get_settings().zero_legion_project_id

DEFAULT_SEARCH_QUERIES = [
    "tiktok shop best selling products 2026",
    "trending tiktok shop products this week",
    "tiktok made me buy it best products 2026",
    "viral tiktok shop products this month",
    "tiktok shop winning products high margin",
    "most sold items tiktok shop today",
    "tiktok shop top sellers beauty skincare",
    "tiktok shop viral gadgets home kitchen",
    "tiktok shop dropshipping winning products supplier",
    "best tiktok shop affiliate products high commission",
]

DEFAULT_NICHES = [
    "beauty", "home", "fitness", "pet", "kitchen",
    "tech accessories", "fashion", "baby", "outdoor",
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
        "max_auto_tasks_per_cycle": 3,
        "high_opportunity_threshold": 50,
        "llm_score_threshold": 40,
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


class TikTokShopService:
    """TikTok Shop Research Agent."""

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
        limit: int = 50,
    ) -> List[TikTokProduct]:
        async with get_session() as session:
            query = select(TikTokProductModel).order_by(
                TikTokProductModel.opportunity_score.desc()
            )
            if status:
                query = query.where(TikTokProductModel.status == status)
            if niche:
                query = query.where(TikTokProductModel.niche == niche)
            if min_score is not None:
                query = query.where(TikTokProductModel.opportunity_score >= min_score)
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
            )
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

    async def delete_product(self, product_id: str) -> bool:
        async with get_session() as session:
            result = await session.execute(
                delete(TikTokProductModel).where(TikTokProductModel.id == product_id)
            )
            return result.rowcount > 0

    # ============================================
    # APPROVAL QUEUE
    # ============================================

    async def list_pending(self, limit: int = 50) -> List[TikTokProduct]:
        """List products pending approval, ordered by opportunity score."""
        return await self.list_products(status="pending_approval", limit=limit)

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

    async def auto_approve_high_confidence(self, threshold: float = 85.0) -> int:
        """Auto-approve products with opportunity score >= threshold."""
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

        Returns list of dicts with: name, category, estimated_price_range,
        why_trending, source_article_title, source_article_url.
        Falls back to raw article titles if LLM is unavailable.
        """
        if not search_results:
            return []

        # Build article summaries for LLM
        articles = []
        for r in search_results[:30]:  # Limit to 30 articles for token budget
            title = r.title if hasattr(r, "title") else str(r)
            snippet = r.snippet if hasattr(r, "snippet") else ""
            url = r.url if hasattr(r, "url") else ""
            articles.append({"title": title, "snippet": snippet[:300], "url": url})

        try:
            import json
            from langchain_core.messages import HumanMessage, SystemMessage

            llm = get_zero_chat_model(task_type="analysis", temperature=0.2)
            llm.num_predict = 4096  # Need more tokens for JSON array

            articles_text = "\n\n".join(
                f"Article: {a['title']}\nSnippet: {a['snippet']}\nURL: {a['url']}"
                for a in articles[:15]  # Limit articles to keep prompt shorter
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
                "Return a JSON array of products. Extract up to 10 unique products.\n"
                "Return ONLY valid JSON, no markdown, no explanation.\n"
                "Keep each entry compact. Example:\n"
                '[{"name":"LED Face Mask","category":"beauty","estimated_price_range":"$25-$45",'
                '"why_trending":"Viral skincare routine product with visible results"}]\n\n'
                f"---ARTICLES---\n{articles_text}"
            )

            llm_response = await llm.ainvoke([
                SystemMessage(content="You extract real sellable product names from articles. Return ONLY a JSON array. /no_think"),
                HumanMessage(content=prompt),
            ])

            result_text = llm_response.content if llm_response else ""

            # Strip markdown code fences if present
            if result_text.startswith("```"):
                lines = result_text.split("\n")
                result_text = "\n".join(
                    lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
                )

            # Try to recover truncated JSON arrays
            result_text = result_text.strip()
            if result_text.startswith("[") and not result_text.endswith("]"):
                # Find last complete JSON object
                last_brace = result_text.rfind("}")
                if last_brace > 0:
                    result_text = result_text[:last_brace + 1] + "]"
                    logger.info("tiktok_json_truncation_recovered")

            products = json.loads(result_text)
            if isinstance(products, list):
                # Validate: filter out entries that look like article titles, not product names
                valid_products = []
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
                    valid_products.append({
                        "name": name[:500],
                        "category": p.get("category", "general"),
                        "estimated_price_range": p.get("estimated_price_range", ""),
                        "why_trending": p.get("why_trending", ""),
                        "source_article_title": p.get("source_title", ""),
                        "source_article_url": p.get("source_url", ""),
                        "is_extracted": True,
                    })
                logger.info("tiktok_llm_extraction_success", count=len(valid_products))
                return valid_products

        except Exception as e:
            logger.warning("tiktok_llm_extraction_failed", error=str(e))

        # LLM failed: return empty rather than polluting DB with article titles
        logger.info("tiktok_extraction_empty_on_failure", article_count=len(search_results))
        return []

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

        for query in DEFAULT_SEARCH_QUERIES:
            try:
                results = await searxng.search(query, num_results=max_results)
                all_results.extend(results)
            except Exception as e:
                errors.append(f"Search failed for '{query}': {e}")

        # Also search per niche
        for niche in DEFAULT_NICHES[:5]:
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

                # Skip if name looks like a duplicate
                if name.lower().strip() in existing_names:
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
                await self._fetch_product_image(product_data["id"], product_data["name"])
                await self._calculate_success_rating(product_data["id"])
                await asyncio.sleep(0.5)
            except Exception as e:
                errors.append(f"Enrichment failed for {product_data['name']}: {e}")

        # Auto-approve products scoring >= 85 (high confidence)
        auto_approved = 0
        try:
            auto_approved = await self.auto_approve_high_confidence(threshold=85.0)
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

        # Enrich with image, sourcing info, and success rating
        await self._fetch_product_image(product_id, product.name)
        await self._generate_sourcing_info(product_id)
        await self._calculate_success_rating(product_id)

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
            from langchain_core.messages import HumanMessage, SystemMessage

            llm = get_zero_chat_model(task_type="analysis", temperature=0.7)

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
                f"4. Content style (educational/review/trending/challenge)\n\n"
                f"Return as JSON array with keys: hook, script, caption, style"
            )

            llm_result = await llm.ainvoke([
                SystemMessage(content="You are a TikTok content strategist. Return ONLY valid JSON."),
                HumanMessage(content=prompt),
            ])
            result = llm_result.content

            import json
            try:
                ideas = json.loads(result)
                if isinstance(ideas, list):
                    # Store ideas on the product
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
            except json.JSONDecodeError:
                logger.warning("tiktok_ideas_json_parse_fail", product_id=product_id)

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

        # Composite
        weights = DEFAULT_CONFIG["scoring_weights"]
        opportunity_score = (
            trend_score * weights["trend"]
            + competition_score * weights["inverse_competition"]
            + margin_score * weights["margin"]
            + actionability * weights["actionability"]
        )

        return {
            "trend_score": round(trend_score, 1),
            "competition_score": round(competition_score, 1),
            "margin_score": round(margin_score, 1),
            "opportunity_score": round(opportunity_score, 1),
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
                from langchain_core.messages import HumanMessage, SystemMessage

                llm = get_zero_chat_model(task_type="analysis", temperature=0.1)

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
                    f"- product_type: 'affiliate', 'dropship', or 'own'\n"
                    f"Return ONLY valid JSON."
                )

                try:
                    llm_response = await llm.ainvoke([
                        SystemMessage(content="You are a TikTok Shop market analyst. Return ONLY valid JSON."),
                        HumanMessage(content=prompt),
                    ])
                    llm_result = llm_response.content if llm_response else None
                except Exception:
                    llm_result = None

                if llm_result:
                    import json
                    try:
                        analysis = json.loads(llm_result)
                        row.llm_analysis = analysis.get("summary", llm_result[:500])
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
                    except json.JSONDecodeError:
                        row.llm_analysis = llm_result[:500]

            except Exception as e:
                logger.warning("tiktok_llm_analysis_failed", product_id=product_id, error=str(e))

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
            success_rating=row.success_rating,
            success_factors=row.success_factors or {},
            supplier_url=row.supplier_url,
            supplier_name=row.supplier_name,
            sourcing_method=row.sourcing_method,
            sourcing_notes=row.sourcing_notes,
            sourcing_links=row.sourcing_links or [],
            listing_steps=row.listing_steps or [],
            discovered_at=row.discovered_at or datetime.utcnow(),
            last_researched_at=row.last_researched_at,
        )

    # ============================================
    # ENRICHMENT: Images, Success Rating, Sourcing
    # ============================================

    async def _fetch_product_image(self, product_id: str, product_name: str) -> Optional[str]:
        """Search for a product image via SearXNG image search and store it."""
        searxng = get_searxng_service()
        queries = [
            f"{product_name} product photo",
            f"{product_name} tiktok shop",
        ]

        for query in queries:
            try:
                results = await searxng.search(query, num_results=5, categories=["images"])
                image_urls = [r.img_src for r in results if r.img_src]
                if not image_urls:
                    # Fallback: use result URLs that look like images
                    image_urls = [
                        r.url for r in results
                        if r.url and any(ext in r.url.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"])
                    ]

                if image_urls:
                    async with get_session() as session:
                        result = await session.execute(
                            select(TikTokProductModel).where(TikTokProductModel.id == product_id)
                        )
                        row = result.scalar_one_or_none()
                        if row:
                            row.image_url = image_urls[0]
                            row.image_urls = image_urls[:5]
                            row.image_search_done = True
                    return image_urls[0]
            except Exception as e:
                logger.debug("tiktok_image_search_error", query=query, error=str(e))

        # Mark as searched even if nothing found
        async with get_session() as session:
            result = await session.execute(
                select(TikTokProductModel).where(TikTokProductModel.id == product_id)
            )
            row = result.scalar_one_or_none()
            if row:
                row.image_search_done = True
        return None

    async def backfill_images(self, limit: int = 20) -> int:
        """Fetch images for approved/active products that don't have them yet."""
        async with get_session() as session:
            result = await session.execute(
                select(TikTokProductModel).where(
                    TikTokProductModel.image_search_done == False,
                    TikTokProductModel.status.in_(["approved", "active", "content_planned", "pending_approval"]),
                ).order_by(TikTokProductModel.opportunity_score.desc()).limit(limit)
            )
            rows = result.scalars().all()
            products = [(r.id, r.name) for r in rows]

        fetched = 0
        for pid, name in products:
            try:
                url = await self._fetch_product_image(pid, name)
                if url:
                    fetched += 1
                await asyncio.sleep(1)  # Rate limit SearXNG
            except Exception:
                pass
        logger.info("tiktok_image_backfill_complete", fetched=fetched, total=len(products))
        return fetched

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

    async def _generate_sourcing_info(self, product_id: str) -> None:
        """Use LLM + SearXNG to generate sourcing information for a product."""
        product = await self.get_product(product_id)
        if not product:
            return

        searxng = get_searxng_service()

        # Search for suppliers
        supplier_results = await searxng.search(
            f"{product.name} supplier wholesale dropship aliexpress",
            num_results=10,
        )

        # Build sourcing links from search results
        sourcing_links = []
        for r in supplier_results:
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

            sourcing_links.append({
                "name": r.title[:200],
                "url": r.url,
                "type": link_type,
                "snippet": (r.snippet or "")[:200],
            })

        # LLM-generated sourcing guide
        try:
            import json
            from langchain_core.messages import HumanMessage, SystemMessage

            llm = get_zero_chat_model(task_type="analysis", temperature=0.2)

            supplier_text = "\n".join(
                f"- {r.title[:100]}: {r.url}" for r in supplier_results[:10]
            )

            prompt = (
                f"Generate a sourcing guide for selling '{product.name}' on TikTok Shop.\n"
                f"Product type: {product.product_type}\n"
                f"Niche: {product.niche or 'general'}\n"
                f"Price range: {product.estimated_price_range or 'Unknown'}\n\n"
                f"Available suppliers found online:\n{supplier_text}\n\n"
                f"Return JSON with:\n"
                f"- sourcing_method: one of 'aliexpress', 'cj_dropshipping', 'tiktok_affiliate', 'direct_wholesale', 'amazon_fba'\n"
                f"- supplier_name: recommended supplier name\n"
                f"- supplier_url: best supplier URL from the list above (must be a real URL from the list)\n"
                f"- sourcing_notes: 2-3 paragraph guide on how to source and list this product\n"
                f"- listing_steps: array of 5-8 step strings for listing on TikTok Shop\n"
                f"Return ONLY valid JSON, no markdown."
            )

            llm_response = await llm.ainvoke([
                SystemMessage(content="You are a TikTok Shop sourcing expert. Return ONLY valid JSON."),
                HumanMessage(content=prompt),
            ])

            result_text = llm_response.content or ""
            if result_text.startswith("```"):
                lines = result_text.split("\n")
                result_text = "\n".join(
                    lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
                )

            result = json.loads(result_text)

            async with get_session() as session:
                db_result = await session.execute(
                    select(TikTokProductModel).where(TikTokProductModel.id == product_id)
                )
                row = db_result.scalar_one_or_none()
                if row:
                    row.sourcing_method = result.get("sourcing_method", "")[:50]
                    row.supplier_name = result.get("supplier_name", "")[:200]
                    row.supplier_url = result.get("supplier_url", "")
                    row.sourcing_notes = result.get("sourcing_notes", "")
                    row.listing_steps = result.get("listing_steps", [])
                    row.sourcing_links = sourcing_links[:10]

            logger.info("tiktok_sourcing_generated", product_id=product_id)

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

        # Fetch image if not already done
        if not product.image_url:
            await self._fetch_product_image(product_id, product.name)

        # Generate sourcing info if missing
        if not product.sourcing_notes:
            await self._generate_sourcing_info(product_id)

        # Calculate success rating
        await self._calculate_success_rating(product_id)

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


@lru_cache()
def get_tiktok_shop_service() -> TikTokShopService:
    """Get cached TikTok Shop service instance."""
    return TikTokShopService()
