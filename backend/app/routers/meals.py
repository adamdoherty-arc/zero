"""
Meal Manager API endpoints.

Covers:
  - Meal service catalog CRUD + seed
  - Menu items per service
  - Promo codes (list + manual add)
  - Card offers (list + manual add)
  - Rebate portal offers (list + manual add)
  - Shipments (list + timeline)
  - Price stacking (per-service + cheapest-across)
  - Manual triggers for catalog refresh, promo hunt, shipment scan, discovery
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.db.models import (
    MealCardOfferModel,
    MealPromoCodeModel,
    MealRebatePortalOfferModel,
    MealServiceModel,
    MealShipmentModel,
)
from app.infrastructure.database import get_session
from app.models.meal import (
    CardOffer,
    CardOfferCreate,
    MealManagerStats,
    MealMenuItem,
    MealMenuItemCreate,
    MealService,
    MealServiceCreate,
    MealServiceStatus,
    MealServiceTier,
    MealServiceUpdate,
    MealShipment,
    PriceStackRequest,
    PriceStackResult,
    PromoCode,
    PromoCodeCreate,
    PromoSource,
    RebatePortal,
    RebatePortalOffer,
    RebatePortalOfferCreate,
)
from app.services.meal_catalog_service import get_meal_catalog_service
from app.services.meal_price_stack_service import get_meal_price_stack_service
from app.services.meal_promo_hunter_service import get_meal_promo_hunter
from app.services.meal_shipment_tracker_service import get_meal_shipment_tracker

router = APIRouter()
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Stats + services
# ---------------------------------------------------------------------------

def _is_active(expires_at: Optional[datetime]) -> bool:
    if expires_at is None:
        return True
    exp = expires_at.replace(tzinfo=None) if expires_at.tzinfo else expires_at
    return exp > datetime.utcnow()


@router.get("/stats", response_model=MealManagerStats)
async def meal_stats():
    async with get_session() as session:
        services = (await session.execute(select(MealServiceModel))).scalars().all()
        tracked = [s for s in services if s.status == MealServiceStatus.TRACKED.value]

        promos = (await session.execute(select(MealPromoCodeModel))).scalars().all()
        active_promo_count = sum(1 for p in promos if _is_active(p.expires_at))

        card_offers = (await session.execute(select(MealCardOfferModel))).scalars().all()
        active_card_count = sum(
            1 for c in card_offers if not c.used and _is_active(c.expires_at)
        )

        portals = (await session.execute(select(MealRebatePortalOfferModel))).scalars().all()
        active_portal_count = sum(1 for p in portals if _is_active(p.expires_at))

        shipments = (await session.execute(select(MealShipmentModel))).scalars().all()
        in_transit = sum(1 for s in shipments if s.status in ("shipped", "out_for_delivery", "processing", "pending"))
        upcoming = sum(1 for s in shipments if s.expected_delivery and _is_active(s.expected_delivery))

    # Compute cheapest across services
    cheapest_price = None
    cheapest_name = None
    try:
        stack_svc = get_meal_price_stack_service()
        quotes = await stack_svc.cheapest_across_services(meal_count=6, new_customer=False)
        if quotes:
            cheapest_price = quotes[0].price_per_meal
            cheapest_name = quotes[0].service_name
    except Exception as e:
        logger.debug("cheapest_compute_failed", error=str(e))

    last_refresh = max([s.last_catalog_refresh_at for s in services if s.last_catalog_refresh_at], default=None)
    last_promo = max([p.last_seen_at for p in promos if p.last_seen_at], default=None)
    last_ship = max([s.updated_at for s in shipments if s.updated_at], default=None)

    return MealManagerStats(
        total_services=len(services),
        tracked_services=len(tracked),
        total_menu_items=await get_meal_catalog_service().count_menu_items(),
        active_promos=active_promo_count,
        active_card_offers=active_card_count,
        active_portal_offers=active_portal_count,
        in_transit_shipments=in_transit,
        upcoming_deliveries=upcoming,
        cheapest_per_meal_usd=cheapest_price,
        cheapest_service_name=cheapest_name,
        last_promo_hunt_at=last_promo,
        last_catalog_refresh_at=last_refresh,
        last_shipment_scan_at=last_ship,
    )


@router.get("/services", response_model=List[MealService])
async def list_services(
    status: Optional[MealServiceStatus] = None,
    tier: Optional[MealServiceTier] = None,
    limit: int = Query(100, ge=1, le=500),
):
    return await get_meal_catalog_service().list_services(status=status, tier=tier, limit=limit)


@router.post("/services", response_model=MealService)
async def create_service(data: MealServiceCreate):
    try:
        return await get_meal_catalog_service().create_service(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/services/{service_id}", response_model=MealService)
async def get_service(service_id: str):
    svc = await get_meal_catalog_service().get_service(service_id)
    if not svc:
        raise HTTPException(status_code=404, detail="meal service not found")
    return svc


@router.patch("/services/{service_id}", response_model=MealService)
async def update_service(service_id: str, data: MealServiceUpdate):
    svc = await get_meal_catalog_service().update_service(service_id, data)
    if not svc:
        raise HTTPException(status_code=404, detail="meal service not found")
    return svc


@router.delete("/services/{service_id}")
async def delete_service(service_id: str):
    ok = await get_meal_catalog_service().delete_service(service_id)
    if not ok:
        raise HTTPException(status_code=404, detail="meal service not found")
    return {"status": "deleted"}


@router.post("/services/seed")
async def seed_services():
    added = await get_meal_catalog_service().seed_defaults()
    return {"added": added}


# ---------------------------------------------------------------------------
# Menu items
# ---------------------------------------------------------------------------

@router.get("/services/{service_id}/menu", response_model=List[MealMenuItem])
async def list_menu_items(service_id: str, limit: int = Query(100, ge=1, le=500)):
    return await get_meal_catalog_service().list_menu_items(service_id, limit=limit)


@router.post("/services/{service_id}/menu", response_model=MealMenuItem)
async def add_menu_item(service_id: str, data: MealMenuItemCreate):
    if data.service_id != service_id:
        raise HTTPException(status_code=400, detail="service_id mismatch")
    return await get_meal_catalog_service().upsert_menu_item(data)


# ---------------------------------------------------------------------------
# Promo codes
# ---------------------------------------------------------------------------

def _row_to_promo(row: MealPromoCodeModel) -> PromoCode:
    return PromoCode(
        id=row.id,
        code=row.code,
        service_id=row.service_id,
        source=PromoSource(row.source) if row.source else PromoSource.OTHER,
        source_url=row.source_url,
        discount_type=row.discount_type,
        discount_value=row.discount_value or 0.0,
        description=row.description,
        min_order=row.min_order,
        new_customer_only=row.new_customer_only,
        stackable=row.stackable,
        verified=row.verified,
        success_rate=row.success_rate,
        times_seen=row.times_seen or 1,
        is_referral=bool(row.is_referral),
        expires_at=row.expires_at,
        first_seen_at=row.first_seen_at or datetime.utcnow(),
        last_seen_at=row.last_seen_at or datetime.utcnow(),
    )


@router.get("/promos", response_model=List[PromoCode])
async def list_promos(
    service_id: Optional[str] = None,
    source: Optional[PromoSource] = None,
    active_only: bool = True,
    limit: int = Query(200, ge=1, le=500),
):
    async with get_session() as session:
        stmt = select(MealPromoCodeModel)
        if service_id:
            stmt = stmt.where(MealPromoCodeModel.service_id == service_id)
        if source:
            stmt = stmt.where(MealPromoCodeModel.source == source.value)
        stmt = stmt.order_by(MealPromoCodeModel.last_seen_at.desc()).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
    result = [_row_to_promo(r) for r in rows]
    if active_only:
        result = [p for p in result if _is_active(p.expires_at)]
    return result


@router.post("/promos", response_model=PromoCode)
async def create_promo(data: PromoCodeCreate):
    async with get_session() as session:
        key = f"{data.service_id or 'generic'}|{data.source.value}|{data.code or ''}|{data.discount_type.value}|{data.discount_value}"
        pid = "promo_" + hashlib.sha1(key.encode()).hexdigest()[:20]
        row = MealPromoCodeModel(
            id=pid,
            code=data.code,
            service_id=data.service_id,
            service_slug_hint=data.service_slug_hint,
            source=data.source.value,
            source_url=data.source_url,
            discount_type=data.discount_type.value,
            discount_value=data.discount_value,
            description=data.description,
            min_order=data.min_order,
            new_customer_only=data.new_customer_only,
            stackable=data.stackable,
            is_referral=data.is_referral,
            expires_at=data.expires_at,
        )
        await session.merge(row)
        await session.flush()
    return _row_to_promo(row)


@router.delete("/promos/{promo_id}")
async def delete_promo(promo_id: str):
    async with get_session() as session:
        row = await session.get(MealPromoCodeModel, promo_id)
        if not row:
            raise HTTPException(status_code=404, detail="promo not found")
        await session.delete(row)
    return {"status": "deleted"}


@router.post("/promos/hunt")
async def hunt_promos(service_id: Optional[str] = None):
    """Manually trigger promo hunt. Scheduler calls hunt_all() every 4h."""
    hunter = get_meal_promo_hunter()
    if service_id:
        return await hunter.hunt_for_service(service_id)
    return await hunter.hunt_all()


# ---------------------------------------------------------------------------
# Card offers
# ---------------------------------------------------------------------------

def _row_to_card(row: MealCardOfferModel) -> CardOffer:
    from app.models.meal import CardNetwork as CN, PromoDiscountType as PDT
    return CardOffer(
        id=row.id,
        network=CN(row.network) if row.network else CN.OTHER,
        card_nickname=row.card_nickname,
        merchant_name=row.merchant_name,
        service_id=row.service_id,
        offer_type=PDT(row.offer_type) if row.offer_type else PDT.DOLLAR,
        value=row.value or 0.0,
        min_spend=row.min_spend,
        expires_at=row.expires_at,
        activated=row.activated,
        used=row.used,
        source=row.source or "manual",
        source_email_id=row.source_email_id,
        notes=row.notes,
        created_at=row.created_at or datetime.utcnow(),
    )


@router.get("/card-offers", response_model=List[CardOffer])
async def list_card_offers(service_id: Optional[str] = None, active_only: bool = True):
    async with get_session() as session:
        stmt = select(MealCardOfferModel)
        if service_id:
            stmt = stmt.where(MealCardOfferModel.service_id == service_id)
        stmt = stmt.order_by(MealCardOfferModel.created_at.desc())
        rows = (await session.execute(stmt)).scalars().all()
    result = [_row_to_card(r) for r in rows]
    if active_only:
        result = [c for c in result if not c.used and _is_active(c.expires_at)]
    return result


@router.post("/card-offers", response_model=CardOffer)
async def create_card_offer(data: CardOfferCreate):
    async with get_session() as session:
        key = f"{data.network.value}|{data.merchant_name}|{data.value}|{data.min_spend}|{data.expires_at}"
        cid = "card_" + hashlib.sha1(key.encode()).hexdigest()[:20]
        row = MealCardOfferModel(
            id=cid,
            network=data.network.value,
            card_nickname=data.card_nickname,
            merchant_name=data.merchant_name,
            service_id=data.service_id,
            offer_type=data.offer_type.value,
            value=data.value,
            min_spend=data.min_spend,
            expires_at=data.expires_at,
            source=data.source,
            source_email_id=data.source_email_id,
            notes=data.notes,
        )
        await session.merge(row)
        await session.flush()
    return _row_to_card(row)


@router.delete("/card-offers/{offer_id}")
async def delete_card_offer(offer_id: str):
    async with get_session() as session:
        row = await session.get(MealCardOfferModel, offer_id)
        if not row:
            raise HTTPException(status_code=404, detail="card offer not found")
        await session.delete(row)
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Rebate portal offers
# ---------------------------------------------------------------------------

def _row_to_portal(row: MealRebatePortalOfferModel) -> RebatePortalOffer:
    return RebatePortalOffer(
        id=row.id,
        portal=RebatePortal(row.portal) if row.portal else RebatePortal.OTHER,
        service_id=row.service_id,
        merchant_name=row.merchant_name,
        cashback_percent=row.cashback_percent or 0.0,
        cashback_flat=row.cashback_flat,
        new_customer_only=row.new_customer_only,
        source_url=row.source_url,
        expires_at=row.expires_at,
        last_seen_at=row.last_seen_at or datetime.utcnow(),
    )


@router.get("/portal-offers", response_model=List[RebatePortalOffer])
async def list_portal_offers(service_id: Optional[str] = None):
    async with get_session() as session:
        stmt = select(MealRebatePortalOfferModel)
        if service_id:
            stmt = stmt.where(MealRebatePortalOfferModel.service_id == service_id)
        stmt = stmt.order_by(MealRebatePortalOfferModel.cashback_percent.desc())
        rows = (await session.execute(stmt)).scalars().all()
    return [_row_to_portal(r) for r in rows]


@router.post("/portal-offers", response_model=RebatePortalOffer)
async def create_portal_offer(data: RebatePortalOfferCreate):
    async with get_session() as session:
        key = f"{data.portal.value}|{data.merchant_name}|{data.new_customer_only}"
        pid = "rebate_" + hashlib.sha1(key.encode()).hexdigest()[:20]
        row = MealRebatePortalOfferModel(
            id=pid,
            portal=data.portal.value,
            service_id=data.service_id,
            merchant_name=data.merchant_name,
            cashback_percent=data.cashback_percent,
            cashback_flat=data.cashback_flat,
            new_customer_only=data.new_customer_only,
            source_url=data.source_url,
            expires_at=data.expires_at,
        )
        await session.merge(row)
        await session.flush()
    return _row_to_portal(row)


# ---------------------------------------------------------------------------
# Shipments
# ---------------------------------------------------------------------------

def _row_to_shipment(row: MealShipmentModel, service_name: Optional[str] = None) -> MealShipment:
    from app.models.meal import ShipmentStatus as SS
    return MealShipment(
        id=row.id,
        service_id=row.service_id,
        service_name=service_name,
        email_id=row.email_id,
        subject=row.subject,
        order_number=row.order_number,
        carrier=row.carrier,
        tracking_number=row.tracking_number,
        tracking_url=row.tracking_url,
        status=SS(row.status) if row.status else SS.PENDING,
        expected_delivery=row.expected_delivery,
        delivered_at=row.delivered_at,
        meal_count=row.meal_count,
        total_charged=row.total_charged,
        created_at=row.created_at or datetime.utcnow(),
        updated_at=row.updated_at or datetime.utcnow(),
    )


@router.get("/shipments", response_model=List[MealShipment])
async def list_shipments(
    service_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
):
    async with get_session() as session:
        stmt = select(MealShipmentModel)
        if service_id:
            stmt = stmt.where(MealShipmentModel.service_id == service_id)
        stmt = stmt.order_by(MealShipmentModel.updated_at.desc()).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()

        services = (await session.execute(select(MealServiceModel))).scalars().all()
        id_to_name = {s.id: s.name for s in services}

    return [_row_to_shipment(r, id_to_name.get(r.service_id)) for r in rows]


@router.post("/shipments/scan")
async def scan_shipments(lookback_days: int = Query(14, ge=1, le=90)):
    tracker = get_meal_shipment_tracker()
    return await tracker.scan_recent(lookback_days=lookback_days)


# ---------------------------------------------------------------------------
# Price stacking
# ---------------------------------------------------------------------------

@router.post("/price-stack", response_model=PriceStackResult)
async def compute_price_stack(req: PriceStackRequest):
    svc = get_meal_price_stack_service()
    try:
        return await svc.calculate(req)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/cheapest", response_model=List[PriceStackResult])
async def cheapest_across(
    meal_count: int = Query(6, ge=1, le=24),
    new_customer: bool = False,
):
    svc = get_meal_price_stack_service()
    return await svc.cheapest_across_services(meal_count=meal_count, new_customer=new_customer)


# ---------------------------------------------------------------------------
# Catalog refresh
# ---------------------------------------------------------------------------

@router.post("/catalog/refresh")
async def refresh_catalog(service_id: Optional[str] = None):
    svc = get_meal_catalog_service()
    if service_id:
        return await svc.refresh_service_catalog(service_id)
    return await svc.refresh_all_catalogs()
