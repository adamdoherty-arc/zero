"""
Meal catalog service.

Owns MealService + MealMenuItem rows: CRUD, seeding, daily catalog refresh.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

import structlog
from sqlalchemy import select, delete, update, func as sa_func

from app.db.models import MealServiceModel, MealMenuItemModel
from app.infrastructure.database import get_session
from app.models.meal import (
    MealService,
    MealServiceCreate,
    MealServiceStatus,
    MealServiceTier,
    MealServiceUpdate,
    MealMenuItem,
    MealMenuItemCreate,
)
from app.services.meal_scraper_service import get_meal_scraper

logger = structlog.get_logger(__name__)


SEED_MEAL_SERVICES: List[dict] = [
    {
        "name": "CookUnity",
        "slug": "cookunity",
        "website_url": "https://www.cookunity.com/",
        "menu_url": "https://www.cookunity.com/menu",
        "tier": MealServiceTier.PREPARED,
        "description": "Chef-crafted prepared meals, premium tier. Rotating weekly menu.",
        "base_price_per_meal": 13.49,
        "min_order_meals": 4,
        "email_sender_patterns": ["@cookunity.com", "cook unity"],
        "tags": ["prepared", "premium", "chef"],
    },
    {
        "name": "Factor",
        "slug": "factor",
        "website_url": "https://www.factor75.com/",
        "menu_url": "https://www.factor75.com/menu",
        "tier": MealServiceTier.PREPARED,
        "description": "Fresh never frozen prepared meals, owned by HelloFresh.",
        "base_price_per_meal": 12.99,
        "min_order_meals": 4,
        "email_sender_patterns": ["@factor75.com", "@factormeals.com", "factor meals"],
        "tags": ["prepared", "low-carb", "keto"],
    },
    {
        "name": "FlexPro Meals",
        "slug": "flexpro-meals",
        "website_url": "https://flexpromeals.com/",
        "menu_url": "https://flexpromeals.com/meals",
        "tier": MealServiceTier.PREPARED,
        "description": "High-protein fitness-focused prepared meals.",
        "base_price_per_meal": 9.99,
        "min_order_meals": 6,
        "email_sender_patterns": ["@flexpromeals.com"],
        "tags": ["prepared", "high-protein", "fitness"],
    },
    {
        "name": "HelloFresh",
        "slug": "hellofresh",
        "website_url": "https://www.hellofresh.com/",
        "menu_url": "https://www.hellofresh.com/recipes/menus",
        "tier": MealServiceTier.MEAL_KIT,
        "description": "Market-leader meal kits. Recipes with pre-portioned ingredients.",
        "base_price_per_meal": 10.99,
        "min_order_meals": 6,
        "email_sender_patterns": ["@hellofresh.com"],
        "tags": ["meal-kit", "family"],
    },
    {
        "name": "EveryPlate",
        "slug": "everyplate",
        "website_url": "https://www.everyplate.com/",
        "menu_url": "https://www.everyplate.com/plans",
        "tier": MealServiceTier.MEAL_KIT,
        "description": "Budget meal kits, owned by HelloFresh.",
        "base_price_per_meal": 5.99,
        "min_order_meals": 6,
        "email_sender_patterns": ["@everyplate.com"],
        "tags": ["meal-kit", "budget"],
    },
    {
        "name": "Home Chef",
        "slug": "home-chef",
        "website_url": "https://www.homechef.com/",
        "menu_url": "https://www.homechef.com/our-menu",
        "tier": MealServiceTier.MEAL_KIT,
        "description": "Flexible meal kits with oven-ready options.",
        "base_price_per_meal": 9.99,
        "min_order_meals": 6,
        "email_sender_patterns": ["@homechef.com"],
        "tags": ["meal-kit", "flexible"],
    },
    {
        "name": "Dinnerly",
        "slug": "dinnerly",
        "website_url": "https://dinnerly.com/",
        "menu_url": "https://dinnerly.com/menu",
        "tier": MealServiceTier.MEAL_KIT,
        "description": "Cheapest meal kit in the US, owned by Marley Spoon.",
        "base_price_per_meal": 4.99,
        "min_order_meals": 6,
        "email_sender_patterns": ["@dinnerly.com"],
        "tags": ["meal-kit", "budget"],
    },
    {
        "name": "Blue Apron",
        "slug": "blue-apron",
        "website_url": "https://www.blueapron.com/",
        "menu_url": "https://www.blueapron.com/menu",
        "tier": MealServiceTier.MEAL_KIT,
        "description": "Meal kits with premium wine pairings.",
        "base_price_per_meal": 9.99,
        "min_order_meals": 6,
        "email_sender_patterns": ["@blueapron.com"],
        "tags": ["meal-kit", "premium"],
    },
    {
        "name": "Green Chef",
        "slug": "green-chef",
        "website_url": "https://www.greenchef.com/",
        "menu_url": "https://www.greenchef.com/menu",
        "tier": MealServiceTier.MEAL_KIT,
        "description": "USDA-organic meal kits, keto/paleo/vegan friendly.",
        "base_price_per_meal": 11.99,
        "min_order_meals": 6,
        "email_sender_patterns": ["@greenchef.com"],
        "tags": ["meal-kit", "organic", "keto", "paleo"],
    },
    {
        "name": "Trifecta",
        "slug": "trifecta",
        "website_url": "https://www.trifectanutrition.com/",
        "menu_url": "https://www.trifectanutrition.com/meals",
        "tier": MealServiceTier.PREPARED,
        "description": "Organic prepared meals for athletes and macro tracking.",
        "base_price_per_meal": 15.12,
        "min_order_meals": 7,
        "email_sender_patterns": ["@trifectanutrition.com"],
        "tags": ["prepared", "organic", "macro", "fitness"],
    },
    {
        "name": "Sunbasket",
        "slug": "sunbasket",
        "website_url": "https://sunbasket.com/",
        "menu_url": "https://sunbasket.com/menu",
        "tier": MealServiceTier.MEAL_KIT,
        "description": "Organic ingredient meal kits.",
        "base_price_per_meal": 10.99,
        "min_order_meals": 6,
        "email_sender_patterns": ["@sunbasket.com"],
        "tags": ["meal-kit", "organic"],
    },
    {
        "name": "HungryRoot",
        "slug": "hungryroot",
        "website_url": "https://www.hungryroot.com/",
        "menu_url": "https://www.hungryroot.com/shop",
        "tier": MealServiceTier.GROCERY,
        "description": "AI-personalized groceries + recipes combo service.",
        "base_price_per_meal": 8.99,
        "min_order_meals": 5,
        "email_sender_patterns": ["@hungryroot.com"],
        "tags": ["grocery", "personalized"],
    },
    {
        "name": "Purple Carrot",
        "slug": "purple-carrot",
        "website_url": "https://www.purplecarrot.com/",
        "menu_url": "https://www.purplecarrot.com/menu",
        "tier": MealServiceTier.MEAL_KIT,
        "description": "Plant-based meal kits and prepared meals.",
        "base_price_per_meal": 11.99,
        "min_order_meals": 6,
        "email_sender_patterns": ["@purplecarrot.com"],
        "tags": ["meal-kit", "plant-based", "vegan"],
    },
    {
        "name": "Thistle",
        "slug": "thistle",
        "website_url": "https://www.thistle.co/",
        "menu_url": "https://www.thistle.co/menu",
        "tier": MealServiceTier.PREPARED,
        "description": "Plant-forward prepared meals and juices (West Coast).",
        "base_price_per_meal": 13.95,
        "min_order_meals": 6,
        "email_sender_patterns": ["@thistle.co"],
        "tags": ["prepared", "plant-based"],
    },
    {
        "name": "Territory Foods",
        "slug": "territory-foods",
        "website_url": "https://www.territoryfoods.com/",
        "menu_url": "https://www.territoryfoods.com/menu",
        "tier": MealServiceTier.PREPARED,
        "description": "Chef-curated prepared meals, Whole30/paleo friendly.",
        "base_price_per_meal": 13.95,
        "min_order_meals": 8,
        "email_sender_patterns": ["@territoryfoods.com"],
        "tags": ["prepared", "whole30", "paleo"],
    },
    {
        "name": "Freshly",
        "slug": "freshly",
        "website_url": "https://www.freshly.com/",
        "menu_url": "https://www.freshly.com/menu",
        "tier": MealServiceTier.PREPARED,
        "description": "Prepared single-serving meals (Nestle-owned).",
        "base_price_per_meal": 9.99,
        "min_order_meals": 6,
        "email_sender_patterns": ["@freshly.com"],
        "tags": ["prepared"],
    },
    {
        "name": "Magic Spoon",
        "slug": "magic-spoon",
        "website_url": "https://magicspoon.com/",
        "menu_url": "https://magicspoon.com/collections/all",
        "tier": MealServiceTier.SUBSCRIPTION_BOX,
        "description": "High-protein low-carb cereal. Often stacks with Rakuten.",
        "base_price_per_meal": 2.75,
        "min_order_meals": 4,
        "email_sender_patterns": ["@magicspoon.com"],
        "tags": ["breakfast", "high-protein"],
    },
    {
        "name": "Daily Harvest",
        "slug": "daily-harvest",
        "website_url": "https://www.daily-harvest.com/",
        "menu_url": "https://www.daily-harvest.com/menu",
        "tier": MealServiceTier.FROZEN,
        "description": "Frozen smoothies, bowls, and plant-based meals.",
        "base_price_per_meal": 8.99,
        "min_order_meals": 9,
        "email_sender_patterns": ["@daily-harvest.com"],
        "tags": ["frozen", "plant-based"],
    },
    {
        "name": "Mosaic Foods",
        "slug": "mosaic-foods",
        "website_url": "https://www.mosaicfoods.com/",
        "menu_url": "https://www.mosaicfoods.com/menu",
        "tier": MealServiceTier.FROZEN,
        "description": "Frozen family-size and single-serve plant-based meals.",
        "base_price_per_meal": 7.99,
        "min_order_meals": 6,
        "email_sender_patterns": ["@mosaicfoods.com"],
        "tags": ["frozen", "plant-based", "family"],
    },
    {
        "name": "Marley Spoon",
        "slug": "marley-spoon",
        "website_url": "https://marleyspoon.com/",
        "menu_url": "https://marleyspoon.com/menu",
        "tier": MealServiceTier.MEAL_KIT,
        "description": "Martha Stewart meal kits.",
        "base_price_per_meal": 9.99,
        "min_order_meals": 6,
        "email_sender_patterns": ["@marleyspoon.com"],
        "tags": ["meal-kit"],
    },
    {
        "name": "Gobble",
        "slug": "gobble",
        "website_url": "https://www.gobble.com/",
        "menu_url": "https://www.gobble.com/menu",
        "tier": MealServiceTier.MEAL_KIT,
        "description": "15-minute meal kits with pre-prepped ingredients.",
        "base_price_per_meal": 11.99,
        "min_order_meals": 6,
        "email_sender_patterns": ["@gobble.com"],
        "tags": ["meal-kit", "fast"],
    },
    {
        "name": "Snap Kitchen",
        "slug": "snap-kitchen",
        "website_url": "https://www.snapkitchen.com/",
        "menu_url": "https://www.snapkitchen.com/menu",
        "tier": MealServiceTier.PREPARED,
        "description": "Texas-based fresh prepared meals, keto and paleo options.",
        "base_price_per_meal": 11.49,
        "min_order_meals": 6,
        "email_sender_patterns": ["@snapkitchen.com"],
        "tags": ["prepared", "keto", "paleo"],
    },
    {
        "name": "MealPro",
        "slug": "mealpro",
        "website_url": "https://mealpro.net/",
        "menu_url": "https://mealpro.net/meals",
        "tier": MealServiceTier.PREPARED,
        "description": "Customizable macros prepared meals.",
        "base_price_per_meal": 11.99,
        "min_order_meals": 6,
        "email_sender_patterns": ["@mealpro.net"],
        "tags": ["prepared", "macros"],
    },
    {
        "name": "Clean Eatz Kitchen",
        "slug": "clean-eatz-kitchen",
        "website_url": "https://cleaneatzkitchen.com/",
        "menu_url": "https://cleaneatzkitchen.com/collections/all-meals",
        "tier": MealServiceTier.PREPARED,
        "description": "Weight-loss and macro-aligned prepared meals.",
        "base_price_per_meal": 8.49,
        "min_order_meals": 6,
        "email_sender_patterns": ["@cleaneatzkitchen.com", "@cleaneatz.com"],
        "tags": ["prepared", "weight-loss"],
    },
    {
        "name": "Ice Age Meals",
        "slug": "ice-age-meals",
        "website_url": "https://iceagemeals.com/",
        "menu_url": "https://iceagemeals.com/collections/all",
        "tier": MealServiceTier.FROZEN,
        "description": "Frozen paleo prepared meals with premium meat.",
        "base_price_per_meal": 13.99,
        "min_order_meals": 6,
        "email_sender_patterns": ["@iceagemeals.com"],
        "tags": ["frozen", "paleo"],
    },
]


def _stable_id(prefix: str, key: str) -> str:
    """Deterministic id so re-seeding is idempotent."""
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _row_to_service(row: MealServiceModel) -> MealService:
    meta = dict(row.metadata_ or {})
    return MealService(
        id=row.id,
        name=row.name,
        slug=row.slug,
        website_url=row.website_url,
        menu_url=row.menu_url,
        email_sender_patterns=list(row.email_sender_patterns or []),
        tier=MealServiceTier(row.tier) if row.tier else MealServiceTier.UNKNOWN,
        status=MealServiceStatus(row.status) if row.status else MealServiceStatus.TRACKED,
        description=row.description,
        base_price_per_meal=row.base_price_per_meal,
        shipping_fee=row.shipping_fee,
        min_order_meals=row.min_order_meals,
        tags=list(row.tags or []),
        notes=row.notes,
        auto_calendar=meta.get("auto_calendar") is not False,  # default True
        last_catalog_refresh_at=row.last_catalog_refresh_at,
        created_at=row.created_at or datetime.utcnow(),
        updated_at=row.updated_at or datetime.utcnow(),
    )


def _row_to_menu_item(row: MealMenuItemModel) -> MealMenuItem:
    return MealMenuItem(
        id=row.id,
        service_id=row.service_id,
        name=row.name,
        description=row.description,
        base_price=row.base_price,
        calories=row.calories,
        protein_g=row.protein_g,
        tags=list(row.tags or []),
        image_url=row.image_url,
        source_url=row.source_url,
        first_seen_at=row.first_seen_at or datetime.utcnow(),
        last_seen_at=row.last_seen_at or datetime.utcnow(),
        available=row.available,
    )


class MealCatalogService:
    """Manages the meal service catalog and per-service menu items."""

    # ------------------------------------------------------------------
    # Seeding
    # ------------------------------------------------------------------

    async def seed_defaults(self) -> int:
        """Insert any missing seed meal services. Returns count added."""
        added = 0
        async with get_session() as session:
            for spec in SEED_MEAL_SERVICES:
                existing = await session.execute(
                    select(MealServiceModel).where(MealServiceModel.slug == spec["slug"])
                )
                if existing.scalar_one_or_none():
                    continue
                row = MealServiceModel(
                    id=_stable_id("meal", spec["slug"]),
                    name=spec["name"],
                    slug=spec["slug"],
                    website_url=spec["website_url"],
                    menu_url=spec.get("menu_url"),
                    email_sender_patterns=spec.get("email_sender_patterns") or [],
                    tier=spec.get("tier", MealServiceTier.UNKNOWN).value,
                    status=MealServiceStatus.TRACKED.value,
                    description=spec.get("description"),
                    base_price_per_meal=spec.get("base_price_per_meal"),
                    shipping_fee=spec.get("shipping_fee"),
                    min_order_meals=spec.get("min_order_meals"),
                    tags=spec.get("tags") or [],
                )
                session.add(row)
                added += 1
        if added:
            logger.info("meal_services_seeded", added=added)
        return added

    # ------------------------------------------------------------------
    # Service CRUD
    # ------------------------------------------------------------------

    async def list_services(
        self,
        *,
        status: Optional[MealServiceStatus] = None,
        tier: Optional[MealServiceTier] = None,
        limit: int = 100,
    ) -> List[MealService]:
        async with get_session() as session:
            stmt = select(MealServiceModel)
            if status:
                stmt = stmt.where(MealServiceModel.status == status.value)
            if tier:
                stmt = stmt.where(MealServiceModel.tier == tier.value)
            stmt = stmt.order_by(MealServiceModel.name.asc()).limit(limit)
            result = await session.execute(stmt)
            return [_row_to_service(r) for r in result.scalars().all()]

    async def get_service(self, service_id: str) -> Optional[MealService]:
        async with get_session() as session:
            row = await session.get(MealServiceModel, service_id)
            return _row_to_service(row) if row else None

    async def get_service_by_slug(self, slug: str) -> Optional[MealService]:
        async with get_session() as session:
            result = await session.execute(
                select(MealServiceModel).where(MealServiceModel.slug == slug)
            )
            row = result.scalar_one_or_none()
            return _row_to_service(row) if row else None

    async def create_service(self, data: MealServiceCreate) -> MealService:
        async with get_session() as session:
            existing = await session.execute(
                select(MealServiceModel).where(MealServiceModel.slug == data.slug)
            )
            if existing.scalar_one_or_none():
                raise ValueError(f"meal service slug already exists: {data.slug}")
            row = MealServiceModel(
                id=_stable_id("meal", data.slug),
                name=data.name,
                slug=data.slug,
                website_url=data.website_url,
                menu_url=data.menu_url,
                email_sender_patterns=data.email_sender_patterns or [],
                tier=data.tier.value,
                status=MealServiceStatus.TRACKED.value,
                description=data.description,
                base_price_per_meal=data.base_price_per_meal,
                shipping_fee=data.shipping_fee,
                min_order_meals=data.min_order_meals,
                tags=data.tags or [],
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return _row_to_service(row)

    async def update_service(
        self, service_id: str, data: MealServiceUpdate
    ) -> Optional[MealService]:
        async with get_session() as session:
            row = await session.get(MealServiceModel, service_id)
            if not row:
                return None
            for field, value in data.model_dump(exclude_unset=True).items():
                if field == "tier" and value is not None:
                    row.tier = value.value if hasattr(value, "value") else value
                elif field == "status" and value is not None:
                    row.status = value.value if hasattr(value, "value") else value
                elif field == "email_sender_patterns":
                    row.email_sender_patterns = list(value) if value else []
                elif field == "tags":
                    row.tags = list(value) if value else []
                elif field == "auto_calendar":
                    meta = dict(row.metadata_ or {})
                    meta["auto_calendar"] = bool(value)
                    row.metadata_ = meta
                else:
                    setattr(row, field, value)
            row.updated_at = datetime.utcnow()
            await session.flush()
            await session.refresh(row)
            return _row_to_service(row)

    async def delete_service(self, service_id: str) -> bool:
        async with get_session() as session:
            row = await session.get(MealServiceModel, service_id)
            if not row:
                return False
            await session.delete(row)
            await session.execute(
                delete(MealMenuItemModel).where(MealMenuItemModel.service_id == service_id)
            )
            return True

    # ------------------------------------------------------------------
    # Menu items
    # ------------------------------------------------------------------

    async def list_menu_items(self, service_id: str, *, limit: int = 100) -> List[MealMenuItem]:
        async with get_session() as session:
            result = await session.execute(
                select(MealMenuItemModel)
                .where(MealMenuItemModel.service_id == service_id)
                .order_by(MealMenuItemModel.last_seen_at.desc())
                .limit(limit)
            )
            return [_row_to_menu_item(r) for r in result.scalars().all()]

    async def upsert_menu_item(self, data: MealMenuItemCreate) -> MealMenuItem:
        async with get_session() as session:
            result = await session.execute(
                select(MealMenuItemModel).where(
                    MealMenuItemModel.service_id == data.service_id,
                    MealMenuItemModel.name == data.name,
                )
            )
            row = result.scalar_one_or_none()
            now = datetime.utcnow()
            if row:
                if data.base_price is not None:
                    row.base_price = data.base_price
                if data.description:
                    row.description = data.description
                if data.calories is not None:
                    row.calories = data.calories
                if data.protein_g is not None:
                    row.protein_g = data.protein_g
                if data.tags:
                    row.tags = list(data.tags)
                if data.image_url:
                    row.image_url = data.image_url
                if data.source_url:
                    row.source_url = data.source_url
                row.last_seen_at = now
                row.available = True
            else:
                row = MealMenuItemModel(
                    id=_stable_id("menu", f"{data.service_id}:{data.name}"),
                    service_id=data.service_id,
                    name=data.name,
                    description=data.description,
                    base_price=data.base_price,
                    calories=data.calories,
                    protein_g=data.protein_g,
                    tags=list(data.tags or []),
                    image_url=data.image_url,
                    source_url=data.source_url,
                    available=True,
                )
                session.add(row)
            await session.flush()
            await session.refresh(row)
            return _row_to_menu_item(row)

    async def count_menu_items(self) -> int:
        async with get_session() as session:
            result = await session.execute(
                select(sa_func.count()).select_from(MealMenuItemModel)
            )
            return int(result.scalar() or 0)

    # ------------------------------------------------------------------
    # Catalog refresh — scrape menu pages for all tracked services
    # ------------------------------------------------------------------

    async def refresh_service_catalog(self, service_id: str) -> dict:
        """Scrape the menu page and log raw markdown as a refresh artifact.

        Menu-page HTML layouts differ per service — automated structured
        extraction is done by LLM in a follow-up (wired by the scheduler job).
        This method just captures the markdown and bumps the timestamp.
        """
        service = await self.get_service(service_id)
        if not service:
            return {"status": "not_found"}
        if not service.menu_url:
            return {"status": "no_menu_url"}

        scraper = get_meal_scraper()
        scraped = await scraper.scrape(service.menu_url)
        now = datetime.utcnow()

        async with get_session() as session:
            row = await session.get(MealServiceModel, service_id)
            if row:
                row.last_catalog_refresh_at = now
                meta = dict(row.metadata_ or {})
                meta["last_scrape_provider"] = scraped.get("provider")
                meta["last_scrape_status"] = scraped.get("status")
                meta["last_scrape_bytes"] = len(scraped.get("markdown", ""))
                row.metadata_ = meta

        return {
            "status": scraped.get("status"),
            "provider": scraped.get("provider"),
            "bytes": len(scraped.get("markdown", "")),
            "markdown": scraped.get("markdown", ""),
        }

    async def refresh_all_catalogs(self) -> dict:
        """Refresh every tracked service. Returns summary."""
        services = await self.list_services(status=MealServiceStatus.TRACKED)
        succeeded = 0
        failed = 0
        for svc in services:
            try:
                result = await self.refresh_service_catalog(svc.id)
                if result.get("status") == "ok":
                    succeeded += 1
                else:
                    failed += 1
            except Exception as e:
                logger.warning("catalog_refresh_failed", service=svc.slug, error=str(e))
                failed += 1
        logger.info("meal_catalog_refresh_complete", total=len(services), ok=succeeded, failed=failed)
        return {"total": len(services), "ok": succeeded, "failed": failed}


_singleton: Optional[MealCatalogService] = None


def get_meal_catalog_service() -> MealCatalogService:
    global _singleton
    if _singleton is None:
        _singleton = MealCatalogService()
    return _singleton
