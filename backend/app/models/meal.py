"""
Meal Manager data models.

Domain:
- MealService: a meal-delivery service (CookUnity, Factor, etc.)
- MealMenuItem: per-service menu item with base price
- PromoCode: discount code scraped from aggregators, merchant sites, or email
- CardOffer: Chase/Amex Offers targeted at a merchant (user-entered or email-derived)
- RebatePortalOffer: cashback percentage at a portal (Rakuten, TopCashback, etc.)
- MealShipment: shipment record derived from Gmail
- MealPriceQuote: a computed best-stacked quote for a given meal/service

All price fields are dollars. All discount percentages are 0-100 floats.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class MealServiceStatus(str, Enum):
    DISCOVERED = "discovered"
    TRACKED = "tracked"
    USED = "used"
    PAUSED = "paused"
    REJECTED = "rejected"


class MealServiceTier(str, Enum):
    PREPARED = "prepared"
    MEAL_KIT = "meal_kit"
    FROZEN = "frozen"
    SUBSCRIPTION_BOX = "subscription_box"
    GROCERY = "grocery"
    UNKNOWN = "unknown"


class PromoSource(str, Enum):
    DIRECT = "direct"
    RAKUTEN = "rakuten"
    RAKUTEN_ADVERTISING = "rakuten_advertising"
    HONEY = "honey"
    RETAILMENOT = "retailmenot"
    COUPERT = "coupert"
    KUDOS = "kudos"
    KNOJI = "knoji"
    CAPITAL_ONE_SHOPPING = "capital_one_shopping"
    SLICKDEALS = "slickdeals"
    REDDIT = "reddit"
    REFERRAL = "referral"
    SIGNUP_INTERCEPT = "signup_intercept"
    VISION = "vision"
    EMAIL = "email"
    MANUAL = "manual"
    COUPONFOLLOW = "couponfollow"
    WETHRIFT = "wethrift"
    OTHER = "other"


class PromoDiscountType(str, Enum):
    PERCENT = "percent"
    DOLLAR = "dollar"
    FREE_SHIPPING = "free_shipping"
    BOGO = "bogo"
    BUNDLE = "bundle"


class CardNetwork(str, Enum):
    CHASE = "chase"
    AMEX = "amex"
    CITI = "citi"
    CAPITAL_ONE = "capital_one"
    DISCOVER = "discover"
    OTHER = "other"


class ShipmentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    DELAYED = "delayed"
    LOST = "lost"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# MealService
# ---------------------------------------------------------------------------

class MealServiceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    slug: str = Field(..., min_length=1, max_length=100)
    website_url: str
    menu_url: Optional[str] = None
    email_sender_patterns: List[str] = Field(default_factory=list)
    tier: MealServiceTier = MealServiceTier.UNKNOWN
    description: Optional[str] = None
    base_price_per_meal: Optional[float] = None
    shipping_fee: Optional[float] = None
    min_order_meals: Optional[int] = None
    tags: List[str] = Field(default_factory=list)


class MealServiceUpdate(BaseModel):
    status: Optional[MealServiceStatus] = None
    menu_url: Optional[str] = None
    email_sender_patterns: Optional[List[str]] = None
    tier: Optional[MealServiceTier] = None
    description: Optional[str] = None
    base_price_per_meal: Optional[float] = None
    shipping_fee: Optional[float] = None
    min_order_meals: Optional[int] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None
    auto_calendar: Optional[bool] = None


class MealService(BaseModel):
    id: str
    name: str
    slug: str
    website_url: str
    menu_url: Optional[str] = None
    email_sender_patterns: List[str] = Field(default_factory=list)
    tier: MealServiceTier = MealServiceTier.UNKNOWN
    status: MealServiceStatus = MealServiceStatus.TRACKED
    description: Optional[str] = None
    base_price_per_meal: Optional[float] = None
    shipping_fee: Optional[float] = None
    min_order_meals: Optional[int] = None
    tags: List[str] = Field(default_factory=list)
    notes: Optional[str] = None
    auto_calendar: bool = True
    last_catalog_refresh_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# MealMenuItem
# ---------------------------------------------------------------------------

class MealMenuItemCreate(BaseModel):
    service_id: str
    name: str = Field(..., min_length=1, max_length=300)
    description: Optional[str] = None
    base_price: Optional[float] = None
    calories: Optional[int] = None
    protein_g: Optional[float] = None
    tags: List[str] = Field(default_factory=list)
    image_url: Optional[str] = None
    source_url: Optional[str] = None


class MealMenuItem(BaseModel):
    id: str
    service_id: str
    name: str
    description: Optional[str] = None
    base_price: Optional[float] = None
    calories: Optional[int] = None
    protein_g: Optional[float] = None
    tags: List[str] = Field(default_factory=list)
    image_url: Optional[str] = None
    source_url: Optional[str] = None
    first_seen_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)
    available: bool = True


# ---------------------------------------------------------------------------
# PromoCode
# ---------------------------------------------------------------------------

class PromoCodeCreate(BaseModel):
    code: Optional[str] = Field(None, max_length=100)  # empty for auto-apply promos
    service_id: Optional[str] = None  # null = generic / multi-merchant
    service_slug_hint: Optional[str] = None  # when service_id not linked yet
    source: PromoSource = PromoSource.OTHER
    source_url: Optional[str] = None
    discount_type: PromoDiscountType = PromoDiscountType.PERCENT
    discount_value: float = 0.0
    description: Optional[str] = None
    min_order: Optional[float] = None
    new_customer_only: bool = False
    stackable: bool = False
    is_referral: bool = False
    expires_at: Optional[datetime] = None


class PromoCode(BaseModel):
    id: str
    code: Optional[str] = None
    service_id: Optional[str] = None
    source: PromoSource
    source_url: Optional[str] = None
    discount_type: PromoDiscountType
    discount_value: float = 0.0
    description: Optional[str] = None
    min_order: Optional[float] = None
    new_customer_only: bool = False
    stackable: bool = False
    verified: bool = False
    success_rate: Optional[float] = None
    times_seen: int = 1
    is_referral: bool = False
    expires_at: Optional[datetime] = None
    first_seen_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# CardOffer (Chase / Amex Offers)
# ---------------------------------------------------------------------------

class CardOfferCreate(BaseModel):
    network: CardNetwork
    card_nickname: Optional[str] = None
    merchant_name: str
    service_id: Optional[str] = None
    offer_type: PromoDiscountType = PromoDiscountType.DOLLAR
    value: float = 0.0
    min_spend: Optional[float] = None
    expires_at: Optional[datetime] = None
    source: str = "manual"  # manual | email
    source_email_id: Optional[str] = None
    notes: Optional[str] = None


class CardOffer(BaseModel):
    id: str
    network: CardNetwork
    card_nickname: Optional[str] = None
    merchant_name: str
    service_id: Optional[str] = None
    offer_type: PromoDiscountType
    value: float = 0.0
    min_spend: Optional[float] = None
    expires_at: Optional[datetime] = None
    activated: bool = False
    used: bool = False
    source: str = "manual"
    source_email_id: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# RebatePortalOffer (Rakuten et al.)
# ---------------------------------------------------------------------------

class RebatePortal(str, Enum):
    RAKUTEN = "rakuten"
    TOPCASHBACK = "topcashback"
    BEFRUGAL = "befrugal"
    CAPITAL_ONE_SHOPPING = "capital_one_shopping"
    OTHER = "other"


class RebatePortalOfferCreate(BaseModel):
    portal: RebatePortal
    service_id: Optional[str] = None
    merchant_name: str
    cashback_percent: float = 0.0
    cashback_flat: Optional[float] = None  # for "$40 back" style deals
    new_customer_only: bool = False
    source_url: Optional[str] = None
    expires_at: Optional[datetime] = None


class RebatePortalOffer(BaseModel):
    id: str
    portal: RebatePortal
    service_id: Optional[str] = None
    merchant_name: str
    cashback_percent: float = 0.0
    cashback_flat: Optional[float] = None
    new_customer_only: bool = False
    source_url: Optional[str] = None
    expires_at: Optional[datetime] = None
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# MealShipment
# ---------------------------------------------------------------------------

class MealShipmentCreate(BaseModel):
    service_id: str
    email_id: Optional[str] = None
    subject: Optional[str] = None
    order_number: Optional[str] = None
    carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    tracking_url: Optional[str] = None
    status: ShipmentStatus = ShipmentStatus.PENDING
    expected_delivery: Optional[datetime] = None
    meal_count: Optional[int] = None
    total_charged: Optional[float] = None


class MealShipment(BaseModel):
    id: str
    service_id: str
    service_name: Optional[str] = None
    email_id: Optional[str] = None
    subject: Optional[str] = None
    order_number: Optional[str] = None
    carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    tracking_url: Optional[str] = None
    status: ShipmentStatus = ShipmentStatus.PENDING
    expected_delivery: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    meal_count: Optional[int] = None
    total_charged: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Price stacking
# ---------------------------------------------------------------------------

class PriceStackComponent(BaseModel):
    kind: str  # "base" | "promo" | "card" | "portal" | "shipping"
    label: str
    amount: float  # negative for discounts, positive for charges (like shipping)
    reference_id: Optional[str] = None
    notes: Optional[str] = None


class PriceStackRequest(BaseModel):
    service_id: str
    meal_count: int = Field(6, ge=1, le=24)
    new_customer: bool = False
    include_shipping: bool = True
    card_network: Optional[CardNetwork] = None
    portal_preference: Optional[RebatePortal] = None


class PriceStackResult(BaseModel):
    service_id: str
    service_name: str
    meal_count: int
    base_subtotal: float
    shipping: float
    total_discounts: float
    total_cashback: float
    final_out_of_pocket: float
    final_after_cashback: float
    price_per_meal: float
    best_promo_id: Optional[str] = None
    best_card_offer_id: Optional[str] = None
    best_portal_offer_id: Optional[str] = None
    components: List[PriceStackComponent] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)
    computed_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

class MealManagerStats(BaseModel):
    total_services: int = 0
    tracked_services: int = 0
    total_menu_items: int = 0
    active_promos: int = 0
    active_card_offers: int = 0
    active_portal_offers: int = 0
    in_transit_shipments: int = 0
    upcoming_deliveries: int = 0
    cheapest_per_meal_usd: Optional[float] = None
    cheapest_service_name: Optional[str] = None
    last_promo_hunt_at: Optional[datetime] = None
    last_catalog_refresh_at: Optional[datetime] = None
    last_shipment_scan_at: Optional[datetime] = None
