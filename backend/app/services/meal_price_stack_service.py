"""
Price stack calculator.

Given a meal service + order size, pick the best combination of:
 - promo code (stackable OR best-single, whichever wins)
 - credit card offer
 - portal cashback

Returns an itemized breakdown showing how the "true price per meal" is built.

Stacking rules (industry standard, roughly):
 - Multiple promo codes: usually NOT allowed, unless flagged stackable=True.
   We pick the single best promo unless two+ are both flagged stackable.
 - Card offer: stacks on top of the promo (applied at statement credit level).
 - Portal cashback: stacks on top of everything else, but rebate portals
   generally disallow promo codes from third parties (e.g., Rakuten voids
   cashback if you use a non-Rakuten code). We surface this as a warning.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import structlog
from sqlalchemy import select

from app.db.models import (
    MealCardOfferModel,
    MealPriceQuoteModel,
    MealPromoCodeModel,
    MealRebatePortalOfferModel,
    MealServiceModel,
)
from app.infrastructure.database import get_session
from app.models.meal import (
    CardNetwork,
    PriceStackComponent,
    PriceStackRequest,
    PriceStackResult,
    PromoDiscountType,
    RebatePortal,
)

logger = structlog.get_logger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _active(expires_at: Optional[datetime]) -> bool:
    if expires_at is None:
        return True
    # Normalize to UTC if tzinfo absent
    now = _now_utc()
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at > now


_MAX_DISCOUNT_RATIO = 0.6  # real single-order promos rarely exceed 60% off


def _apply_discount(subtotal: float, discount_type: str, value: float) -> float:
    """Return the dollar amount discounted (positive number).

    Sanity-capped at 60% of subtotal. Many "$100 off" promos are actually
    multi-week welcome offers. Without the cap, a $100 promo on a $80
    single-order subtotal would wipe the bill to $0, which overstates
    the user's real first-order savings.
    """
    if subtotal <= 0:
        return 0.0
    cap = subtotal * _MAX_DISCOUNT_RATIO
    if discount_type == PromoDiscountType.PERCENT.value:
        raw = subtotal * (value / 100.0)
    elif discount_type == PromoDiscountType.DOLLAR.value:
        raw = min(value, subtotal)
    elif discount_type == PromoDiscountType.FREE_SHIPPING.value:
        return 0.0  # shipping is handled separately
    elif discount_type == PromoDiscountType.BOGO.value:
        raw = subtotal * 0.25
    else:
        raw = 0.0
    return round(min(raw, cap), 2)


class MealPriceStackService:
    async def calculate(self, req: PriceStackRequest) -> PriceStackResult:
        async with get_session() as session:
            svc_row = await session.get(MealServiceModel, req.service_id)
            if not svc_row:
                raise ValueError(f"unknown meal service: {req.service_id}")

            base_price = svc_row.base_price_per_meal or 0.0
            base_subtotal = round(base_price * req.meal_count, 2)
            shipping = (svc_row.shipping_fee or 0.0) if req.include_shipping else 0.0

            # Load candidate promos targeting this service (or generic)
            promo_rows = (
                await session.execute(
                    select(MealPromoCodeModel).where(
                        (MealPromoCodeModel.service_id == req.service_id)
                        | (MealPromoCodeModel.service_id.is_(None))
                    )
                )
            ).scalars().all()

            active_promos = [
                p for p in promo_rows
                if _active(p.expires_at)
                and (not p.new_customer_only or req.new_customer)
                and (p.min_order is None or base_subtotal >= (p.min_order or 0))
            ]

            # Load card offers for this merchant
            card_rows = (
                await session.execute(
                    select(MealCardOfferModel).where(
                        MealCardOfferModel.service_id == req.service_id
                    )
                )
            ).scalars().all()

            if req.card_network:
                card_rows = [c for c in card_rows if c.network == req.card_network.value]
            active_cards = [
                c for c in card_rows
                if _active(c.expires_at) and not c.used
                and (c.min_spend is None or base_subtotal >= (c.min_spend or 0))
            ]

            # Load portal offers
            portal_rows = (
                await session.execute(
                    select(MealRebatePortalOfferModel).where(
                        MealRebatePortalOfferModel.service_id == req.service_id
                    )
                )
            ).scalars().all()
            if req.portal_preference:
                portal_rows = [p for p in portal_rows if p.portal == req.portal_preference.value]
            active_portals = [
                p for p in portal_rows
                if _active(p.expires_at)
                and (not p.new_customer_only or req.new_customer)
            ]

        # --- Build components
        components: List[PriceStackComponent] = []
        notes: List[str] = []

        components.append(PriceStackComponent(
            kind="base",
            label=f"{req.meal_count} meals @ ${base_price:.2f}",
            amount=base_subtotal,
        ))
        if shipping > 0:
            components.append(PriceStackComponent(
                kind="shipping",
                label="Shipping",
                amount=shipping,
            ))

        # --- Pick best promo (or best stackable pair)
        promo_discount = 0.0
        best_promo_id: Optional[str] = None
        if active_promos:
            scored = [
                (p, _apply_discount(base_subtotal, p.discount_type, p.discount_value))
                for p in active_promos
            ]
            scored.sort(key=lambda x: x[1], reverse=True)
            top_promo, top_disc = scored[0]

            # Stacking: if top is stackable, try to find another stackable to combine
            if top_promo.stackable:
                for p2, d2 in scored[1:]:
                    if p2.stackable and p2.id != top_promo.id:
                        combined_disc = top_disc + _apply_discount(
                            base_subtotal - top_disc, p2.discount_type, p2.discount_value
                        )
                        if combined_disc > top_disc:
                            promo_discount = combined_disc
                            best_promo_id = top_promo.id
                            components.append(PriceStackComponent(
                                kind="promo",
                                label=f"Promo: {top_promo.code or top_promo.description or 'auto'} ({top_promo.source})",
                                amount=-top_disc,
                                reference_id=top_promo.id,
                            ))
                            components.append(PriceStackComponent(
                                kind="promo",
                                label=f"Stacked promo: {p2.code or p2.description or 'auto'} ({p2.source})",
                                amount=-(combined_disc - top_disc),
                                reference_id=p2.id,
                            ))
                            break
            if promo_discount == 0.0:
                promo_discount = top_disc
                best_promo_id = top_promo.id
                components.append(PriceStackComponent(
                    kind="promo",
                    label=f"Promo: {top_promo.code or top_promo.description or 'auto'} ({top_promo.source})",
                    amount=-top_disc,
                    reference_id=top_promo.id,
                ))
            # Free-shipping promo: zero out shipping
            if top_promo.discount_type == PromoDiscountType.FREE_SHIPPING.value and shipping > 0:
                components.append(PriceStackComponent(
                    kind="promo",
                    label="Free shipping",
                    amount=-shipping,
                    reference_id=top_promo.id,
                ))
                shipping = 0.0

        # --- Pick best card offer
        card_discount = 0.0
        best_card_id: Optional[str] = None
        if active_cards:
            scored_c = [
                (c, _apply_discount(base_subtotal, c.offer_type, c.value))
                for c in active_cards
            ]
            scored_c.sort(key=lambda x: x[1], reverse=True)
            top_card, card_discount = scored_c[0]
            best_card_id = top_card.id
            components.append(PriceStackComponent(
                kind="card",
                label=f"{top_card.network.upper()} Offer: {top_card.merchant_name}",
                amount=-card_discount,
                reference_id=top_card.id,
                notes="Applied as statement credit after purchase posts",
            ))

        out_of_pocket = round(
            max(0.0, base_subtotal + shipping - promo_discount - card_discount), 2
        )

        # --- Portal cashback (calculated on after-tax subtotal post-code typically;
        # we approximate using the subtotal after promo)
        cashback = 0.0
        best_portal_id: Optional[str] = None
        if active_portals:
            # Rakuten voids cashback if third-party code used — flag it
            if promo_discount > 0 and any(
                p.portal == RebatePortal.RAKUTEN.value for p in active_portals
            ):
                notes.append(
                    "Rakuten typically voids cashback when a non-Rakuten promo code is used. "
                    "Prefer the single highest-value stack."
                )
            scored_p = []
            for p in active_portals:
                subtotal_for_cb = max(0.0, base_subtotal - promo_discount)
                cb = round(subtotal_for_cb * (p.cashback_percent or 0.0) / 100.0, 2)
                if p.cashback_flat:
                    cb = max(cb, p.cashback_flat)
                scored_p.append((p, cb))
            scored_p.sort(key=lambda x: x[1], reverse=True)
            top_portal, cashback = scored_p[0]
            best_portal_id = top_portal.id
            components.append(PriceStackComponent(
                kind="portal",
                label=f"{top_portal.portal.title()} cashback: {top_portal.cashback_percent:.1f}%",
                amount=-cashback,
                reference_id=top_portal.id,
                notes="Cashback paid to portal account, typically weeks later",
            ))

        after_cashback = round(max(0.0, out_of_pocket - cashback), 2)
        price_per_meal = round(after_cashback / max(1, req.meal_count), 2)

        result = PriceStackResult(
            service_id=req.service_id,
            service_name=svc_row.name,
            meal_count=req.meal_count,
            base_subtotal=base_subtotal,
            shipping=shipping,
            total_discounts=round(promo_discount + card_discount, 2),
            total_cashback=cashback,
            final_out_of_pocket=out_of_pocket,
            final_after_cashback=after_cashback,
            price_per_meal=price_per_meal,
            best_promo_id=best_promo_id,
            best_card_offer_id=best_card_id,
            best_portal_offer_id=best_portal_id,
            components=components,
            notes=notes,
        )

        # Persist the quote
        try:
            async with get_session() as session:
                qid = hashlib.sha1(
                    f"{req.service_id}:{req.meal_count}:{result.computed_at.isoformat()}".encode()
                ).hexdigest()[:24]
                session.add(MealPriceQuoteModel(
                    id=f"quote_{qid}",
                    service_id=req.service_id,
                    meal_count=req.meal_count,
                    new_customer=req.new_customer,
                    base_subtotal=base_subtotal,
                    shipping=shipping,
                    total_discounts=result.total_discounts,
                    total_cashback=result.total_cashback,
                    final_out_of_pocket=result.final_out_of_pocket,
                    final_after_cashback=result.final_after_cashback,
                    price_per_meal=result.price_per_meal,
                    best_promo_id=best_promo_id,
                    best_card_offer_id=best_card_id,
                    best_portal_offer_id=best_portal_id,
                    components=[c.model_dump() for c in components],
                    notes=notes,
                ))
        except Exception as e:
            logger.debug("meal_price_quote_persist_failed", error=str(e))

        return result

    async def cheapest_across_services(
        self, *, meal_count: int = 6, new_customer: bool = False
    ) -> List[PriceStackResult]:
        """Compute stack for every tracked service, sorted cheapest-first."""
        async with get_session() as session:
            services = (
                await session.execute(
                    select(MealServiceModel).where(
                        MealServiceModel.status == "tracked",
                        MealServiceModel.base_price_per_meal.is_not(None),
                    )
                )
            ).scalars().all()

        results = []
        for s in services:
            try:
                r = await self.calculate(PriceStackRequest(
                    service_id=s.id,
                    meal_count=meal_count,
                    new_customer=new_customer,
                ))
                results.append(r)
            except Exception as e:
                logger.debug("price_stack_service_failed", service=s.slug, error=str(e))
        results.sort(key=lambda r: r.price_per_meal)
        return results


_singleton: Optional[MealPriceStackService] = None


def get_meal_price_stack_service() -> MealPriceStackService:
    global _singleton
    if _singleton is None:
        _singleton = MealPriceStackService()
    return _singleton
