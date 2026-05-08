"""
Meal shipment tracker — reads Gmail for meal delivery notifications.

Matches emails against each tracked MealService's `email_sender_patterns`,
extracts shipment metadata (order #, tracking #, carrier, ETA, charge amount),
and upserts into meal_shipments.

Also opportunistically extracts Chase/Amex Offers activation emails and
writes them into meal_card_offers.
"""

from __future__ import annotations

import hashlib
import json as _json
import re
from datetime import date as _date, datetime, timedelta, timezone
from typing import Any, List, Optional

import structlog
from sqlalchemy import select

from app.db.models import (
    EmailCacheModel,
    MealCardOfferModel,
    MealServiceModel,
    MealShipmentModel,
)
from app.infrastructure.database import get_session
from app.models.calendar import EventCreate, EventDateTime, EventReminder, EventVisibility
from app.models.meal import (
    CardNetwork,
    PromoDiscountType,
    ShipmentStatus,
)

try:
    from app.services.calendar_service import get_calendar_service
except Exception:  # pragma: no cover
    get_calendar_service = None  # type: ignore

try:
    from app.infrastructure.unified_llm_client import get_unified_llm_client
except Exception:  # pragma: no cover
    get_unified_llm_client = None  # type: ignore

logger = structlog.get_logger(__name__)


CARRIER_RE = re.compile(r"\b(UPS|USPS|FedEx|DHL|OnTrac|LSO|GSO)\b", re.IGNORECASE)
TRACKING_RE = re.compile(
    r"\b(1Z[0-9A-Z]{16}|\d{12,22}|[A-Z]{2}\d{9}US|JD\d{18})\b"
)
TRACKING_URL_RE = re.compile(
    r"https?://[^\s<>\"]+(?:track|tracking|shipment|parcel)[^\s<>\"]*",
    re.IGNORECASE,
)
ORDER_RE = re.compile(r"(?:order|confirmation)[\s#:]*([A-Z0-9\-]{5,25})", re.IGNORECASE)
TOTAL_RE = re.compile(r"(?:total|charged|amount)[\s:]*\$(\d+(?:\.\d{2})?)", re.IGNORECASE)
MEAL_COUNT_RE = re.compile(r"(\d+)\s*meals?", re.IGNORECASE)
ETA_RE = re.compile(
    r"(?:arriv(?:e|al|ing)|deliver(?:y|ed|ing)|expected)[^.\n]*?"
    r"(\w+day,?\s+[A-Za-z]+\s+\d{1,2}|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)",
    re.IGNORECASE,
)
AMEX_OFFER_RE = re.compile(
    r"(?:spend|earn)\s*\$?(\d+(?:\.\d{2})?)\s*(?:or more)?,?\s*(?:get|receive)\s*\$?(\d+(?:\.\d{2})?)",
    re.IGNORECASE,
)
CHASE_OFFER_RE = re.compile(
    r"(\d+)%\s*(?:cash\s*back|back)(?:\s+at\s+([A-Za-z][A-Za-z0-9 &\-]+))?",
    re.IGNORECASE,
)


def _classify_status(subject: str, body: str) -> ShipmentStatus:
    text = (subject + " " + body).lower()
    if "delivered" in text:
        return ShipmentStatus.DELIVERED
    if "out for delivery" in text:
        return ShipmentStatus.OUT_FOR_DELIVERY
    if "delay" in text:
        return ShipmentStatus.DELAYED
    if "shipped" in text or "on its way" in text or "has shipped" in text:
        return ShipmentStatus.SHIPPED
    if "processing" in text or "prepared" in text:
        return ShipmentStatus.PROCESSING
    if "cancel" in text:
        return ShipmentStatus.CANCELLED
    return ShipmentStatus.PENDING


class MealShipmentTrackerService:
    async def scan_recent(self, *, lookback_days: int = 14) -> dict:
        """Scan the Gmail cache for meal service emails.

        This reads `email_cache` (already populated by the existing Gmail sync),
        so it never hits Gmail's API directly. It runs hourly and is idempotent
        because we key shipments by (service_id, order_number) or (email_id).
        """
        async with get_session() as session:
            services = (
                await session.execute(
                    select(MealServiceModel).where(
                        MealServiceModel.status == "tracked"
                    )
                )
            ).scalars().all()

        if not services:
            return {"status": "no_services"}

        # Build two parallel pattern indexes per service:
        #   domain_patterns:  "@factor75.com" -> service (matches sender domain
        #                     using suffix logic so subdomains work too)
        #   phrase_patterns:  "cook unity"    -> service (free-text brand name
        #                     checked against sender email + display name)
        domain_patterns: list[tuple[str, MealServiceModel]] = []
        phrase_patterns: list[tuple[str, MealServiceModel]] = []
        for svc in services:
            for pat in (svc.email_sender_patterns or []):
                p = pat.strip().lower()
                if not p:
                    continue
                if p.startswith("@") or "." in p:
                    domain_patterns.append((p.lstrip("@"), svc))
                else:
                    phrase_patterns.append((p, svc))

        if not domain_patterns and not phrase_patterns:
            return {"status": "no_patterns"}

        async with get_session() as session:
            # Pull recent emails from the local cache
            from datetime import timedelta
            since = datetime.utcnow() - timedelta(days=lookback_days)
            rows = (
                await session.execute(
                    select(EmailCacheModel).where(
                        EmailCacheModel.received_at >= since
                    ).order_by(EmailCacheModel.received_at.desc())
                )
            ).scalars().all()

        shipments_upserted = 0
        card_offers_upserted = 0
        examined = 0

        for email in rows:
            examined += 1
            from_addr = email.from_address or {}
            sender_email = (from_addr.get("email") or "").lower() if isinstance(from_addr, dict) else ""
            sender_name = (from_addr.get("name") or "").lower() if isinstance(from_addr, dict) else ""
            sender = f"{sender_email} {sender_name}".strip()
            sender_domain = sender_email.split("@")[-1] if "@" in sender_email else ""
            subject = (email.subject or "")

            # Match against each service's patterns
            matched_svc: Optional[MealServiceModel] = None
            # 1) domain-suffix match (handles "noreply@notifications.factor75.com"
            #    vs. pattern "@factor75.com")
            if sender_domain:
                for domain, svc in domain_patterns:
                    if sender_domain == domain or sender_domain.endswith("." + domain):
                        matched_svc = svc
                        break
            # 2) free-text brand phrase fallback ("cook unity" matches either
            #    the email or the display name)
            if not matched_svc and sender:
                for phrase, svc in phrase_patterns:
                    if phrase in sender:
                        matched_svc = svc
                        break
            if matched_svc:
                if await self._upsert_shipment(matched_svc, email):
                    shipments_upserted += 1
                continue

            # Otherwise: check for Chase/Amex Offers email relevant to a merchant
            if any(k in sender for k in ("chase.com", "americanexpress.com", "amex.com")):
                if await self._try_extract_card_offer(email, services):
                    card_offers_upserted += 1

        logger.info(
            "meal_shipment_scan_complete",
            examined=examined,
            shipments=shipments_upserted,
            card_offers=card_offers_upserted,
        )
        return {
            "status": "ok",
            "examined": examined,
            "shipments": shipments_upserted,
            "card_offers": card_offers_upserted,
        }

    # ------------------------------------------------------------------
    # Shipment upsert
    # ------------------------------------------------------------------

    async def _upsert_shipment(
        self, svc: MealServiceModel, email: EmailCacheModel
    ) -> bool:
        subject = email.subject or ""
        body = (email.body_text or email.snippet or "")[:20000]

        carrier_m = CARRIER_RE.search(subject + " " + body)
        tracking_m = TRACKING_RE.search(body)
        tracking_url_m = TRACKING_URL_RE.search(body)
        order_m = ORDER_RE.search(subject + " " + body)
        total_m = TOTAL_RE.search(body)
        meal_count_m = MEAL_COUNT_RE.search(body)

        status = _classify_status(subject, body)
        order_number = order_m.group(1) if order_m else None
        eta = await self._extract_delivery_date(subject, body, email.received_at)

        key = (
            f"{svc.id}|{order_number}"
            if order_number
            else f"{svc.id}|{email.id}"
        )
        sid = "ship_" + hashlib.sha1(key.encode()).hexdigest()[:20]

        async with get_session() as session:
            existing = None
            if order_number:
                existing = (
                    await session.execute(
                        select(MealShipmentModel).where(
                            MealShipmentModel.service_id == svc.id,
                            MealShipmentModel.order_number == order_number,
                        )
                    )
                ).scalar_one_or_none()
            if not existing:
                existing = await session.get(MealShipmentModel, sid)

            now = datetime.utcnow()
            if existing:
                prior_status = existing.status
                prior_eta = existing.expected_delivery
                # Only update if this email is fresher signal (later or higher status)
                if status.value != existing.status:
                    existing.status = status.value
                if tracking_m and not existing.tracking_number:
                    existing.tracking_number = tracking_m.group(1)
                if tracking_url_m and not existing.tracking_url:
                    existing.tracking_url = tracking_url_m.group(0)
                if carrier_m and not existing.carrier:
                    existing.carrier = carrier_m.group(1).upper()
                if eta and not existing.expected_delivery:
                    existing.expected_delivery = eta
                if status == ShipmentStatus.DELIVERED and not existing.delivered_at:
                    existing.delivered_at = email.received_at or now
                existing.updated_at = now
                # Sync calendar event on meaningful changes
                await session.flush()
                await self._sync_calendar_event(
                    session, existing, svc,
                    was_new=False, prior_status=prior_status, prior_eta=prior_eta,
                )
                return False

            row = MealShipmentModel(
                id=sid,
                service_id=svc.id,
                email_id=email.id,
                subject=subject[:500],
                order_number=order_number,
                carrier=carrier_m.group(1).upper() if carrier_m else None,
                tracking_number=tracking_m.group(1) if tracking_m else None,
                tracking_url=tracking_url_m.group(0) if tracking_url_m else None,
                status=status.value,
                expected_delivery=eta,
                meal_count=int(meal_count_m.group(1)) if meal_count_m else None,
                total_charged=float(total_m.group(1)) if total_m else None,
                delivered_at=(email.received_at or now) if status == ShipmentStatus.DELIVERED else None,
                raw_body=body[:10000],
            )
            session.add(row)
            await session.flush()
            await self._sync_calendar_event(session, row, svc, was_new=True)
            return True

    # ------------------------------------------------------------------
    # Delivery-date extraction (regex fast path + LLM fallback)
    # ------------------------------------------------------------------

    async def _extract_delivery_date(
        self, subject: str, body: str, email_received_at: Optional[datetime]
    ) -> Optional[datetime]:
        """Parse expected delivery date from the email. Fast regex first,
        LLM fallback if that produces nothing usable.
        """
        ref_year = (email_received_at or datetime.utcnow()).year
        haystack = f"{subject}\n{body}"

        # Fast path: explicit ISO dates (2026-04-28)
        iso = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", haystack)
        if iso:
            try:
                return datetime(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)), tzinfo=timezone.utc)
            except ValueError:
                pass

        # Fast path: "MM/DD/YYYY" or "MM/DD"
        mdy = re.search(
            r"\b(?:arriv(?:e|al|ing)|deliver(?:y|ed|ing)|expected|eta)\s*[^.\n]{0,40}?"
            r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?",
            haystack,
            re.IGNORECASE,
        )
        if mdy:
            try:
                mo = int(mdy.group(1))
                dy = int(mdy.group(2))
                yr = mdy.group(3)
                if yr:
                    yr = int(yr)
                    if yr < 100:
                        yr += 2000
                else:
                    yr = ref_year
                return datetime(yr, mo, dy, tzinfo=timezone.utc)
            except ValueError:
                pass

        # Fast path: "Thursday, April 25" or "April 25"
        month_names = r"(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        m = re.search(
            rf"(?:arriv(?:e|al|ing)|deliver(?:y|ed|ing)|expected|eta)[^.\n]*?{month_names}\s+(\d{{1,2}})",
            haystack,
            re.IGNORECASE,
        )
        if m:
            try:
                from datetime import datetime as _dt
                mo = _dt.strptime(m.group(1)[:3], "%b").month
                dy = int(m.group(2))
                return datetime(ref_year, mo, dy, tzinfo=timezone.utc)
            except ValueError:
                pass

        # LLM fallback
        if get_unified_llm_client is None:
            return None
        prompt = f"""Extract the expected delivery date from this meal-kit / food-delivery shipment email.
Reply with JSON only: {{"date": "YYYY-MM-DD", "confidence": "high|medium|low"}}.
If no clear date, reply {{"date": null, "confidence": "low"}}.
Today is {(email_received_at or datetime.utcnow()).date().isoformat()}.

Subject: {subject[:200]}

Body:
{body[:3000]}
"""
        try:
            raw = await get_unified_llm_client().chat(
                prompt=prompt,
                task_type="meal_eta_extract",
                temperature=0.0,
                max_tokens=120,
                json_mode=True,
            )
            data = _json.loads(raw) if raw.strip().startswith("{") else _json.loads(
                raw.strip().strip("`").removeprefix("json").strip() or "{}"
            )
            if (data.get("confidence") or "").lower() == "low":
                return None
            iso = data.get("date")
            if not iso:
                return None
            return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)
        except Exception as e:
            logger.debug("eta_llm_extract_failed", error=str(e))
            return None

    # ------------------------------------------------------------------
    # Calendar event sync
    # ------------------------------------------------------------------

    async def _sync_calendar_event(
        self,
        session,
        shipment: MealShipmentModel,
        svc: MealServiceModel,
        *,
        was_new: bool,
        prior_status: Optional[str] = None,
        prior_eta: Optional[datetime] = None,
    ) -> None:
        """Create / update / settle the Google Calendar event for a shipment.

        Respects the per-service toggle at ``MealServiceModel.metadata_.auto_calendar``
        (default ON). Skips quietly when calendar is not connected.
        """
        if get_calendar_service is None:
            return
        meta = dict(svc.metadata_ or {})
        auto = meta.get("auto_calendar")
        if auto is False:  # explicit opt-out only
            return
        if not shipment.expected_delivery:
            return

        calendar = get_calendar_service()
        event_id = shipment.calendar_event_id

        # Terminal states: cancel or mark delivered
        if shipment.status in ("cancelled", "lost"):
            if event_id:
                try:
                    await calendar.delete_event(event_id)
                except Exception as e:
                    logger.debug("delivery_event_delete_failed", error=str(e), event_id=event_id)
                shipment.calendar_event_id = None
            return

        event = self._build_delivery_event(shipment, svc)

        try:
            if not event_id:
                created = await calendar.create_event(event)
                shipment.calendar_event_id = created.id
                logger.info(
                    "delivery_event_created",
                    shipment=shipment.id,
                    service=svc.slug,
                    event_id=created.id,
                    date=event.start.date,
                )
            else:
                # Only reissue if status changed OR ETA shifted
                eta_changed = prior_eta != shipment.expected_delivery
                status_changed = prior_status != shipment.status
                if eta_changed or status_changed:
                    # Google's update_event uses EventUpdate schema; easiest to delete+recreate
                    # on ETA change to keep logic simple (event IDs are cheap).
                    try:
                        await calendar.delete_event(event_id)
                    except Exception:
                        pass
                    created = await calendar.create_event(event)
                    shipment.calendar_event_id = created.id
                    logger.info(
                        "delivery_event_rebuilt",
                        shipment=shipment.id,
                        service=svc.slug,
                        event_id=created.id,
                        eta_changed=eta_changed,
                        status_changed=status_changed,
                    )
        except Exception as e:
            logger.warning(
                "delivery_event_sync_failed",
                shipment=shipment.id,
                service=svc.slug,
                error=str(e),
            )

    def _build_delivery_event(
        self, shipment: MealShipmentModel, svc: MealServiceModel
    ) -> EventCreate:
        """Assemble the all-day EventCreate for a shipment's delivery date."""
        eta: datetime = shipment.expected_delivery  # type: ignore[assignment]
        if eta.tzinfo is None:
            eta = eta.replace(tzinfo=timezone.utc)
        date_str = eta.date().isoformat()
        end_str = (eta.date() + timedelta(days=1)).isoformat()

        if shipment.status == "delivered":
            summary = f"✅ {svc.name} delivered"
            reminders: list[EventReminder] = []
        else:
            summary = f"🍱 {svc.name} delivery"
            reminders = [EventReminder(method="popup", minutes=1440)]

        lines: list[str] = []
        if shipment.order_number:
            lines.append(f"Order #{shipment.order_number}")
        if shipment.tracking_url:
            lines.append(f"Tracking: {shipment.tracking_url}")
        elif shipment.tracking_number:
            lines.append(f"Tracking #: {shipment.tracking_number}")
        if shipment.carrier:
            lines.append(f"Carrier: {shipment.carrier}")
        if shipment.meal_count:
            lines.append(f"Meals: {shipment.meal_count}")
        if shipment.total_charged:
            lines.append(f"Charged: ${shipment.total_charged:.2f}")
        lines.append(f"Status: {shipment.status}")
        lines.append("Auto-created by Zero meal manager.")

        return EventCreate(
            summary=summary,
            description="\n".join(lines),
            start=EventDateTime(date=date_str),
            end=EventDateTime(date=end_str),
            reminders=reminders,
            visibility=EventVisibility.DEFAULT,
        )

    # ------------------------------------------------------------------
    # Card offer extraction
    # ------------------------------------------------------------------

    async def _try_extract_card_offer(
        self, email: EmailCacheModel, services: List[MealServiceModel]
    ) -> bool:
        """Best-effort extract from Chase/Amex Offers email.

        Matches the merchant name in the body against our tracked services and
        records the offer. Many of these emails are generic marketing; we only
        record ones we confidently matched to a known meal service.
        """
        subject = (email.subject or "").lower()
        body = (email.body_text or email.snippet or "")[:20000]
        from_addr = email.from_address or {}
        sender = ""
        if isinstance(from_addr, dict):
            sender = f"{from_addr.get('email', '') or ''} {from_addr.get('name', '') or ''}".lower()

        # Only process emails that clearly describe an offer for a merchant
        if "offer" not in subject and "offer" not in body.lower():
            return False

        matched: Optional[MealServiceModel] = None
        for svc in services:
            if svc.name.lower() in body.lower():
                matched = svc
                break
        if not matched:
            return False

        network = CardNetwork.CHASE if "chase" in sender else CardNetwork.AMEX

        amex_m = AMEX_OFFER_RE.search(body) if network == CardNetwork.AMEX else None
        chase_m = CHASE_OFFER_RE.search(body) if network == CardNetwork.CHASE else None

        if amex_m:
            min_spend = float(amex_m.group(1))
            value = float(amex_m.group(2))
            offer_type = PromoDiscountType.DOLLAR.value
        elif chase_m:
            value = float(chase_m.group(1))
            min_spend = None
            offer_type = PromoDiscountType.PERCENT.value
        else:
            return False

        key = f"{network.value}|{matched.id}|{email.id}"
        cid = "card_" + hashlib.sha1(key.encode()).hexdigest()[:20]

        async with get_session() as session:
            if await session.get(MealCardOfferModel, cid):
                return False
            session.add(MealCardOfferModel(
                id=cid,
                network=network.value,
                merchant_name=matched.name,
                service_id=matched.id,
                offer_type=offer_type,
                value=value,
                min_spend=min_spend,
                source="email",
                source_email_id=email.id,
                notes=subject[:300],
            ))
            return True


_singleton: Optional[MealShipmentTrackerService] = None


def get_meal_shipment_tracker() -> MealShipmentTrackerService:
    global _singleton
    if _singleton is None:
        _singleton = MealShipmentTrackerService()
    return _singleton
