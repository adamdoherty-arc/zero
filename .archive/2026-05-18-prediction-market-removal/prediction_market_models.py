"""
Prediction Market data models.
Models for Kalshi + Polymarket market tracking, bettor analysis, and research.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class Platform(str, Enum):
    """Prediction market platform."""
    KALSHI = "kalshi"
    POLYMARKET = "polymarket"


class MarketCategory(str, Enum):
    """Category of prediction market."""
    POLITICS = "politics"
    ECONOMICS = "economics"
    SPORTS = "sports"
    CRYPTO = "crypto"
    WEATHER = "weather"
    SCIENCE = "science"
    ENTERTAINMENT = "entertainment"
    TECHNOLOGY = "technology"
    OTHER = "other"


class MarketStatus(str, Enum):
    """Status of a prediction market."""
    OPEN = "open"
    CLOSED = "closed"
    SETTLED = "settled"


# ---------------------------------------------------------------------------
# Market Models
# ---------------------------------------------------------------------------

class PredictionMarketCreate(BaseModel):
    """Schema for creating/upserting a prediction market."""
    platform: Platform
    ticker: str = Field(..., min_length=1, max_length=200)
    title: str = Field(..., min_length=1)
    category: MarketCategory = MarketCategory.OTHER
    yes_price: float = Field(0.0, ge=0, le=1)
    no_price: float = Field(0.0, ge=0, le=1)
    volume: float = Field(0.0, ge=0)
    open_interest: int = Field(0, ge=0)
    status: MarketStatus = MarketStatus.OPEN
    close_time: Optional[datetime] = None
    result: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = None


class PredictionMarket(BaseModel):
    """Full prediction market model."""
    id: str
    platform: Platform
    ticker: str
    title: str
    category: MarketCategory = MarketCategory.OTHER
    yes_price: float = 0.0
    no_price: float = 0.0
    volume: float = 0.0
    open_interest: int = 0
    status: MarketStatus = MarketStatus.OPEN
    close_time: Optional[datetime] = None
    result: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = None
    last_synced_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Bettor Models
# ---------------------------------------------------------------------------

class PredictionBettorCreate(BaseModel):
    """Schema for creating/upserting a tracked bettor."""
    platform: Platform
    bettor_address: str = Field(..., min_length=1, max_length=200)
    display_name: Optional[str] = None


class PredictionBettor(BaseModel):
    """Full bettor profile model."""
    id: str
    platform: Platform
    bettor_address: str
    display_name: Optional[str] = None
    total_trades: int = 0
    win_count: int = 0
    loss_count: int = 0
    win_rate: float = 0.0
    total_volume: float = 0.0
    pnl_total: float = 0.0
    avg_bet_size: float = 0.0
    best_streak: int = 0
    current_streak: int = 0
    categories: List[str] = Field(default_factory=list)
    composite_score: float = 0.0
    last_active_at: Optional[datetime] = None
    tracked_since: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Snapshot Models
# ---------------------------------------------------------------------------

class PredictionSnapshot(BaseModel):
    """Price snapshot for a market at a point in time."""
    id: str
    market_id: str
    yes_price: float = 0.0
    no_price: float = 0.0
    volume: float = 0.0
    snapshot_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Stats & Reports
# ---------------------------------------------------------------------------

class PredictionMarketStats(BaseModel):
    """Aggregate statistics for prediction market system."""
    total_markets: int = 0
    open_markets: int = 0
    kalshi_markets: int = 0
    polymarket_markets: int = 0
    total_bettors_tracked: int = 0
    avg_bettor_win_rate: float = 0.0
    top_bettor_pnl: float = 0.0
    total_volume: float = 0.0
    last_kalshi_sync: Optional[datetime] = None
    last_polymarket_sync: Optional[datetime] = None
    last_push_to_ada: Optional[datetime] = None
    snapshots_24h: int = 0


class QualityReport(BaseModel):
    """Quality report for Claude oversight."""
    collection_health: Dict[str, Any] = Field(default_factory=dict)
    bettor_tracking: Dict[str, Any] = Field(default_factory=dict)
    research_quality: Dict[str, Any] = Field(default_factory=dict)
    push_health: Dict[str, Any] = Field(default_factory=dict)
    legion_status: Optional[Dict[str, Any]] = None


class LegionProgressReport(BaseModel):
    """Legion sprint execution progress."""
    zero_sprint: Optional[Dict[str, Any]] = None
    ada_sprints: List[Dict[str, Any]] = Field(default_factory=list)
    overall_completion: float = 0.0
    blocked_tasks: int = 0
    quality_score: float = 0.0
