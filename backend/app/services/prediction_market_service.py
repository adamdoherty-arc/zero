"""
Prediction Market Intelligence Service.
Collects prediction market data from Kalshi + Polymarket, tracks top bettors,
captures price snapshots, and pushes aggregated data to ADA.
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from functools import lru_cache
import structlog
import httpx

from sqlalchemy import select, update, func as sql_func, delete

from app.infrastructure.database import get_session
from app.infrastructure.config import get_settings
from app.infrastructure.circuit_breaker import get_circuit_breaker
from app.db.models import (
    PredictionMarketModel,
    PredictionBettorModel,
    PredictionSnapshotModel,
)
from app.models.prediction_market import (
    PredictionMarket,
    PredictionBettor,
    PredictionSnapshot,
    PredictionMarketStats,
    QualityReport,
    Platform,
    MarketCategory,
    MarketStatus,
)
from app.services.searxng_service import get_searxng_service

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Category detection from market title / tags
# ---------------------------------------------------------------------------

_CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    MarketCategory.POLITICS.value: [
        "election", "president", "congress", "senate", "vote", "republican",
        "democrat", "biden", "trump", "governor", "legislation", "bill",
        "impeach", "filibuster", "cabinet", "political",
    ],
    MarketCategory.ECONOMICS.value: [
        "gdp", "inflation", "unemployment", "fed", "interest rate", "recession",
        "stock", "s&p", "nasdaq", "dow", "treasury", "cpi", "jobs report",
        "housing", "trade deficit",
    ],
    MarketCategory.SPORTS.value: [
        "nfl", "nba", "mlb", "nhl", "soccer", "football", "basketball",
        "baseball", "super bowl", "world series", "championship", "playoff",
        "mvp", "match", "game", "tennis", "golf",
    ],
    MarketCategory.CRYPTO.value: [
        "bitcoin", "btc", "ethereum", "eth", "crypto", "token", "blockchain",
        "defi", "nft", "solana", "dogecoin", "altcoin",
    ],
    MarketCategory.WEATHER.value: [
        "hurricane", "temperature", "weather", "tornado", "earthquake",
        "flood", "climate", "drought", "wildfire", "snowfall",
    ],
    MarketCategory.SCIENCE.value: [
        "nasa", "spacex", "launch", "rover", "vaccine", "clinical trial",
        "fda", "approval", "research", "study", "discovery", "ai model",
    ],
    MarketCategory.ENTERTAINMENT.value: [
        "oscar", "grammy", "emmy", "box office", "movie", "album",
        "concert", "streaming", "netflix", "disney", "spotify",
    ],
    MarketCategory.TECHNOLOGY.value: [
        "apple", "google", "microsoft", "meta", "openai", "chatgpt",
        "iphone", "android", "chip", "semiconductor", "ai", "quantum",
        "starlink", "spacex", "tesla",
    ],
}


def _detect_category(title: str) -> str:
    """Detect market category from title using keyword matching."""
    title_lower = title.lower()
    best_cat = MarketCategory.OTHER.value
    best_hits = 0

    for cat, keywords in _CATEGORY_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in title_lower)
        if hits > best_hits:
            best_hits = hits
            best_cat = cat

    return best_cat


def _generate_id(prefix: str = "pm") -> str:
    """Generate a short unique ID with a prefix."""
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


# ---------------------------------------------------------------------------
# ORM <-> Pydantic converters
# ---------------------------------------------------------------------------

def _market_to_pydantic(row: PredictionMarketModel) -> PredictionMarket:
    return PredictionMarket(
        id=row.id,
        platform=row.platform,
        ticker=row.ticker,
        title=row.title,
        category=row.category,
        yes_price=row.yes_price,
        no_price=row.no_price,
        volume=row.volume,
        open_interest=row.open_interest,
        status=row.status,
        close_time=row.close_time,
        result=row.result,
        raw_data=row.raw_data,
        last_synced_at=row.last_synced_at,
        created_at=row.created_at,
    )


def _bettor_to_pydantic(row: PredictionBettorModel) -> PredictionBettor:
    return PredictionBettor(
        id=row.id,
        platform=row.platform,
        bettor_address=row.bettor_address,
        display_name=row.display_name,
        total_trades=row.total_trades,
        win_count=row.win_count,
        loss_count=row.loss_count,
        win_rate=row.win_rate,
        total_volume=row.total_volume,
        pnl_total=row.pnl_total,
        avg_bet_size=row.avg_bet_size,
        best_streak=row.best_streak,
        current_streak=row.current_streak,
        categories=row.categories or [],
        composite_score=row.composite_score,
        last_active_at=row.last_active_at,
        tracked_since=row.tracked_since,
    )


def _snapshot_to_pydantic(row: PredictionSnapshotModel) -> PredictionSnapshot:
    return PredictionSnapshot(
        id=row.id,
        market_id=row.market_id,
        yes_price=row.yes_price,
        no_price=row.no_price,
        volume=row.volume,
        snapshot_at=row.snapshot_at,
    )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class PredictionMarketService:
    """Collects prediction market data from Kalshi + Polymarket, tracks top bettors."""

    def __init__(self):
        self.settings = get_settings()
        self._client: Optional[httpx.AsyncClient] = None
        self._kalshi_breaker = get_circuit_breaker(
            "kalshi",
            failure_threshold=5,
            recovery_timeout=60.0,
        )
        self._polymarket_breaker = get_circuit_breaker(
            "polymarket",
            failure_threshold=5,
            recovery_timeout=60.0,
        )
        self._ada_breaker = get_circuit_breaker(
            "ada",
            failure_threshold=3,
            recovery_timeout=120.0,
        )

    @property
    def client(self) -> httpx.AsyncClient:
        """Get or create a persistent HTTP client for connection reuse."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    # =========================================================================
    # SYNC: KALSHI
    # =========================================================================

    async def sync_kalshi_markets(self) -> dict:
        """Fetch active markets from Kalshi API, upsert into DB."""
        now = datetime.now(timezone.utc)
        stats = {"markets_synced": 0, "new_markets": 0, "errors": []}

        async def _fetch():
            url = f"{self.settings.kalshi_api_url}/markets"
            headers = {}
            if self.settings.kalshi_api_key:
                headers["Authorization"] = f"Bearer {self.settings.kalshi_api_key}"

            response = await self.client.get(
                url,
                params={"status": "open", "limit": 200},
                headers=headers,
            )
            response.raise_for_status()
            return response.json()

        try:
            data = await self._kalshi_breaker.call(_fetch)
        except Exception as exc:
            error_msg = f"Kalshi API error: {exc}"
            logger.error("kalshi_sync_failed", error=str(exc))
            stats["errors"].append(error_msg)
            return stats

        markets_raw = data.get("markets", [])
        if not markets_raw and isinstance(data, list):
            markets_raw = data

        async with get_session() as session:
            # Load existing tickers for upsert
            existing_q = await session.execute(
                select(PredictionMarketModel.ticker).where(
                    PredictionMarketModel.platform == Platform.KALSHI.value
                )
            )
            existing_tickers = {row[0] for row in existing_q.all()}

            for raw in markets_raw:
                try:
                    ticker = raw.get("ticker", raw.get("id", ""))
                    if not ticker:
                        continue

                    title = raw.get("title", raw.get("question", ""))
                    yes_price = float(raw.get("yes_price", raw.get("last_price", 0)) or 0) / 100.0
                    no_price = 1.0 - yes_price if yes_price > 0 else 0.0
                    volume = float(raw.get("volume", raw.get("dollar_volume", 0)) or 0)
                    open_interest = int(raw.get("open_interest", 0) or 0)
                    category = _detect_category(title)

                    close_time = None
                    close_str = raw.get("close_time", raw.get("expiration_time"))
                    if close_str:
                        try:
                            close_time = datetime.fromisoformat(
                                close_str.replace("Z", "+00:00")
                            )
                        except (ValueError, TypeError):
                            pass

                    if ticker in existing_tickers:
                        # Update existing
                        await session.execute(
                            update(PredictionMarketModel)
                            .where(
                                PredictionMarketModel.ticker == ticker,
                                PredictionMarketModel.platform == Platform.KALSHI.value,
                            )
                            .values(
                                title=title,
                                yes_price=yes_price,
                                no_price=no_price,
                                volume=volume,
                                open_interest=open_interest,
                                category=category,
                                close_time=close_time,
                                status=MarketStatus.OPEN.value,
                                raw_data=raw,
                                last_synced_at=now,
                            )
                        )
                    else:
                        # Insert new
                        session.add(PredictionMarketModel(
                            id=_generate_id("km"),
                            platform=Platform.KALSHI.value,
                            ticker=ticker,
                            title=title,
                            category=category,
                            yes_price=yes_price,
                            no_price=no_price,
                            volume=volume,
                            open_interest=open_interest,
                            status=MarketStatus.OPEN.value,
                            close_time=close_time,
                            raw_data=raw,
                            last_synced_at=now,
                        ))
                        stats["new_markets"] += 1

                    stats["markets_synced"] += 1
                except Exception as exc:
                    stats["errors"].append(f"Kalshi market parse error: {exc}")

        logger.info(
            "kalshi_sync_complete",
            synced=stats["markets_synced"],
            new=stats["new_markets"],
            errors=len(stats["errors"]),
        )
        return stats

    # =========================================================================
    # SYNC: POLYMARKET
    # =========================================================================

    async def sync_polymarket_markets(self) -> dict:
        """Fetch active markets from Polymarket Gamma API, upsert into DB."""
        now = datetime.now(timezone.utc)
        stats = {"markets_synced": 0, "new_markets": 0, "errors": []}

        async def _fetch():
            url = f"{self.settings.polymarket_gamma_url}/events"
            response = await self.client.get(
                url,
                params={"active": "true", "limit": 100},
            )
            response.raise_for_status()
            return response.json()

        try:
            data = await self._polymarket_breaker.call(_fetch)
        except Exception as exc:
            error_msg = f"Polymarket API error: {exc}"
            logger.error("polymarket_sync_failed", error=str(exc))
            stats["errors"].append(error_msg)
            return stats

        # Polymarket returns events, each with nested markets
        events = data if isinstance(data, list) else data.get("events", data.get("data", []))

        async with get_session() as session:
            existing_q = await session.execute(
                select(PredictionMarketModel.ticker).where(
                    PredictionMarketModel.platform == Platform.POLYMARKET.value
                )
            )
            existing_tickers = {row[0] for row in existing_q.all()}

            for event in events:
                try:
                    # Each event may contain multiple markets
                    markets_in_event = event.get("markets", [event])

                    for market in markets_in_event:
                        condition_id = market.get("conditionId", market.get("condition_id", ""))
                        slug = market.get("slug", market.get("question_id", ""))
                        ticker = condition_id or slug or market.get("id", "")
                        if not ticker:
                            continue

                        title = market.get("question", market.get("title", event.get("title", "")))
                        # Polymarket prices are 0-1 floats
                        yes_price = float(market.get("outcomePrices", [0, 0])[0] if isinstance(
                            market.get("outcomePrices"), list
                        ) else market.get("bestBid", market.get("lastTradePrice", 0)) or 0)
                        no_price = 1.0 - yes_price if yes_price > 0 else 0.0
                        volume = float(market.get("volume", market.get("volumeNum", 0)) or 0)
                        open_interest = int(market.get("liquidity", market.get("openInterest", 0)) or 0)
                        category = _detect_category(title)

                        close_time = None
                        end_date = market.get("endDate", market.get("end_date_iso"))
                        if end_date:
                            try:
                                close_time = datetime.fromisoformat(
                                    end_date.replace("Z", "+00:00")
                                )
                            except (ValueError, TypeError):
                                pass

                        if ticker in existing_tickers:
                            await session.execute(
                                update(PredictionMarketModel)
                                .where(
                                    PredictionMarketModel.ticker == ticker,
                                    PredictionMarketModel.platform == Platform.POLYMARKET.value,
                                )
                                .values(
                                    title=title,
                                    yes_price=yes_price,
                                    no_price=no_price,
                                    volume=volume,
                                    open_interest=open_interest,
                                    category=category,
                                    close_time=close_time,
                                    status=MarketStatus.OPEN.value,
                                    raw_data=market,
                                    last_synced_at=now,
                                )
                            )
                        else:
                            session.add(PredictionMarketModel(
                                id=_generate_id("poly"),
                                platform=Platform.POLYMARKET.value,
                                ticker=ticker,
                                title=title,
                                category=category,
                                yes_price=yes_price,
                                no_price=no_price,
                                volume=volume,
                                open_interest=open_interest,
                                status=MarketStatus.OPEN.value,
                                close_time=close_time,
                                raw_data=market,
                                last_synced_at=now,
                            ))
                            stats["new_markets"] += 1

                        stats["markets_synced"] += 1

                except Exception as exc:
                    stats["errors"].append(f"Polymarket event parse error: {exc}")

        logger.info(
            "polymarket_sync_complete",
            synced=stats["markets_synced"],
            new=stats["new_markets"],
            errors=len(stats["errors"]),
        )
        return stats

    # =========================================================================
    # PRICE SNAPSHOTS
    # =========================================================================

    async def capture_price_snapshots(self) -> dict:
        """Snapshot current prices for all open markets."""
        now = datetime.now(timezone.utc)
        snapshot_count = 0
        errors = []

        async with get_session() as session:
            result = await session.execute(
                select(PredictionMarketModel).where(
                    PredictionMarketModel.status == MarketStatus.OPEN.value
                )
            )
            open_markets = result.scalars().all()

            for market in open_markets:
                try:
                    snapshot = PredictionSnapshotModel(
                        id=_generate_id("snap"),
                        market_id=market.id,
                        yes_price=market.yes_price,
                        no_price=market.no_price,
                        volume=market.volume,
                        snapshot_at=now,
                    )
                    session.add(snapshot)
                    snapshot_count += 1
                except Exception as exc:
                    errors.append(f"Snapshot error for {market.id}: {exc}")

            # Prune snapshots older than 7 days to keep table manageable
            cutoff = now - timedelta(days=7)
            await session.execute(
                delete(PredictionSnapshotModel).where(
                    PredictionSnapshotModel.snapshot_at < cutoff
                )
            )

        logger.info("price_snapshots_captured", count=snapshot_count, errors=len(errors))
        return {"snapshots_created": snapshot_count, "errors": errors}

    # =========================================================================
    # TOP BETTORS DISCOVERY
    # =========================================================================

    async def discover_top_bettors(self) -> dict:
        """Discover top bettors from platform leaderboards via SearXNG."""
        stats = {"discovered": 0, "updated": 0, "errors": []}
        searxng = get_searxng_service()

        search_queries = [
            "polymarket top bettors leaderboard 2026",
            "kalshi leaderboard top traders 2026",
            "polymarket whale wallets top PnL",
            "prediction market best traders performance",
        ]

        discovered_bettors: List[Dict[str, Any]] = []

        for query in search_queries:
            try:
                results = await searxng.search(query, num_results=10)
                for r in results:
                    snippet = r.snippet.lower() if r.snippet else ""
                    title = r.title.lower() if r.title else ""
                    combined = f"{title} {snippet}"

                    # Extract potential wallet addresses (0x...) or usernames
                    # Polymarket uses Ethereum-style addresses
                    import re
                    addresses = re.findall(r'0x[a-fA-F0-9]{6,42}', combined)
                    for addr in addresses:
                        discovered_bettors.append({
                            "platform": Platform.POLYMARKET.value,
                            "bettor_address": addr.lower(),
                            "display_name": None,
                            "source_url": r.url,
                        })

                    # Look for named bettors with stats patterns
                    # e.g., "username: 73% win rate" or "trader XYZ made $50k"
                    name_patterns = re.findall(
                        r'(?:trader|bettor|user)\s+["\']?(\w{3,30})["\']?',
                        combined,
                    )
                    for name in name_patterns:
                        platform = Platform.POLYMARKET.value
                        if "kalshi" in combined:
                            platform = Platform.KALSHI.value
                        discovered_bettors.append({
                            "platform": platform,
                            "bettor_address": name.lower(),
                            "display_name": name,
                            "source_url": r.url,
                        })

                await asyncio.sleep(0.5)
            except Exception as exc:
                stats["errors"].append(f"Search error for '{query}': {exc}")

        # Deduplicate by address
        seen_addresses: set = set()
        unique_bettors: List[Dict[str, Any]] = []
        for b in discovered_bettors:
            key = f"{b['platform']}:{b['bettor_address']}"
            if key not in seen_addresses:
                seen_addresses.add(key)
                unique_bettors.append(b)

        # Upsert into DB
        async with get_session() as session:
            existing_q = await session.execute(
                select(PredictionBettorModel.bettor_address)
            )
            existing_addresses = {row[0] for row in existing_q.all()}

            for bettor in unique_bettors:
                addr = bettor["bettor_address"]
                if addr in existing_addresses:
                    # Update display_name if we found one and it was missing
                    if bettor.get("display_name"):
                        await session.execute(
                            update(PredictionBettorModel)
                            .where(PredictionBettorModel.bettor_address == addr)
                            .values(display_name=bettor["display_name"])
                        )
                    stats["updated"] += 1
                else:
                    session.add(PredictionBettorModel(
                        id=_generate_id("bet"),
                        platform=bettor["platform"],
                        bettor_address=addr,
                        display_name=bettor.get("display_name"),
                        total_trades=0,
                        win_count=0,
                        loss_count=0,
                        win_rate=0.0,
                        total_volume=0.0,
                        pnl_total=0.0,
                        avg_bet_size=0.0,
                        best_streak=0,
                        current_streak=0,
                        categories=[],
                        composite_score=0.0,
                    ))
                    stats["discovered"] += 1
                    existing_addresses.add(addr)

        logger.info(
            "bettors_discovered",
            discovered=stats["discovered"],
            updated=stats["updated"],
            errors=len(stats["errors"]),
        )
        return stats

    # =========================================================================
    # BETTOR STATS UPDATE
    # =========================================================================

    async def update_bettor_stats(self) -> dict:
        """Recalculate composite scores for all tracked bettors."""
        stats = {"updated": 0, "errors": []}

        async with get_session() as session:
            result = await session.execute(select(PredictionBettorModel))
            bettors = result.scalars().all()

            for bettor in bettors:
                try:
                    # Recalculate win_rate from counts
                    total = bettor.win_count + bettor.loss_count
                    if total > 0:
                        bettor.win_rate = round(bettor.win_count / total, 4)
                    else:
                        bettor.win_rate = 0.0

                    # Calculate composite score:
                    # (win_rate * 0.4) + (normalized_pnl * 0.3) + (normalized_trades * 0.3)
                    win_component = bettor.win_rate * 0.4
                    pnl_component = min(bettor.pnl_total / 10000.0, 1.0) * 0.3 if bettor.pnl_total > 0 else 0.0
                    trades_component = min(bettor.total_trades / 100.0, 1.0) * 0.3

                    bettor.composite_score = round(
                        (win_component + pnl_component + trades_component) * 100,
                        2,
                    )
                    stats["updated"] += 1
                except Exception as exc:
                    stats["errors"].append(f"Bettor {bettor.id} update error: {exc}")

        logger.info("bettor_stats_updated", updated=stats["updated"], errors=len(stats["errors"]))
        return stats

    # =========================================================================
    # RESEARCH INSIGHTS
    # =========================================================================

    async def research_market_insights(self) -> dict:
        """SearXNG search for prediction market analysis and strategies."""
        stats = {"findings": 0, "errors": []}
        searxng = get_searxng_service()

        queries = [
            "prediction market analysis 2026",
            "polymarket strategies tips",
            "kalshi betting insights analysis",
            "prediction market arbitrage opportunities",
            "prediction markets accuracy track record",
        ]

        all_findings: List[Dict[str, Any]] = []

        for query in queries:
            try:
                results = await searxng.search(query, num_results=10)
                for r in results:
                    snippet = r.snippet or ""
                    title = r.title or ""
                    text = f"{title} {snippet}".lower()

                    # Score relevance
                    relevance = 30
                    high_value_kw = [
                        "strategy", "analysis", "insight", "prediction market",
                        "polymarket", "kalshi", "arbitrage", "win rate",
                        "profitable", "returns", "edge", "alpha",
                    ]
                    for kw in high_value_kw:
                        if kw in text:
                            relevance += 8

                    relevance = min(95, relevance)

                    all_findings.append({
                        "title": title,
                        "url": r.url,
                        "snippet": snippet[:300],
                        "source_engine": r.engine,
                        "relevance_score": relevance,
                        "query": query,
                    })

                await asyncio.sleep(0.5)
            except Exception as exc:
                stats["errors"].append(f"Research search error for '{query}': {exc}")

        stats["findings"] = len(all_findings)

        # Store top findings as raw_data on a sentinel market or log them
        if all_findings:
            top_findings = sorted(
                all_findings,
                key=lambda f: f["relevance_score"],
                reverse=True,
            )[:20]
            logger.info(
                "market_research_complete",
                total_findings=len(all_findings),
                top_score=top_findings[0]["relevance_score"] if top_findings else 0,
            )

        return stats

    # =========================================================================
    # ADA PUSH
    # =========================================================================

    async def push_to_ada(self) -> dict:
        """Push latest prediction market data to ADA via HTTP POST."""
        now = datetime.now(timezone.utc)
        cutoff_24h = now - timedelta(hours=24)

        # Gather data to push
        async with get_session() as session:
            # Markets
            market_q = await session.execute(
                select(PredictionMarketModel)
                .where(PredictionMarketModel.status == MarketStatus.OPEN.value)
                .order_by(PredictionMarketModel.volume.desc())
                .limit(200)
            )
            markets = market_q.scalars().all()

            # Bettors
            bettor_q = await session.execute(
                select(PredictionBettorModel)
                .order_by(PredictionBettorModel.composite_score.desc())
                .limit(100)
            )
            bettors = bettor_q.scalars().all()

            # Recent snapshots (24h)
            snap_q = await session.execute(
                select(PredictionSnapshotModel)
                .where(PredictionSnapshotModel.snapshot_at >= cutoff_24h)
                .order_by(PredictionSnapshotModel.snapshot_at.desc())
            )
            snapshots = snap_q.scalars().all()

        payload = {
            "markets": [
                {
                    "id": m.id,
                    "platform": m.platform,
                    "ticker": m.ticker,
                    "title": m.title,
                    "category": m.category,
                    "yes_price": m.yes_price,
                    "no_price": m.no_price,
                    "volume": m.volume,
                    "open_interest": m.open_interest,
                    "status": m.status,
                    "close_time": m.close_time.isoformat() if m.close_time else None,
                }
                for m in markets
            ],
            "bettors": [
                {
                    "id": b.id,
                    "platform": b.platform,
                    "bettor_address": b.bettor_address,
                    "display_name": b.display_name,
                    "win_rate": b.win_rate,
                    "pnl_total": b.pnl_total,
                    "total_trades": b.total_trades,
                    "composite_score": b.composite_score,
                }
                for b in bettors
            ],
            "snapshots": [
                {
                    "id": s.id,
                    "market_id": s.market_id,
                    "yes_price": s.yes_price,
                    "no_price": s.no_price,
                    "volume": s.volume,
                    "snapshot_at": s.snapshot_at.isoformat() if s.snapshot_at else None,
                }
                for s in snapshots
            ],
            "pushed_at": now.isoformat(),
        }

        ada_url = f"{self.settings.ada_api_url}/api/prediction-market-ingest/batch"

        async def _push():
            headers = {"Content-Type": "application/json"}
            if self.settings.ada_api_token:
                headers["Authorization"] = f"Bearer {self.settings.ada_api_token}"
            response = await self.client.post(ada_url, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()

        try:
            result = await self._ada_breaker.call(_push)
            logger.info(
                "ada_push_complete",
                markets=len(payload["markets"]),
                bettors=len(payload["bettors"]),
                snapshots=len(payload["snapshots"]),
            )
            return {
                "success": True,
                "markets_pushed": len(payload["markets"]),
                "bettors_pushed": len(payload["bettors"]),
                "snapshots_pushed": len(payload["snapshots"]),
                "ada_response": result,
            }
        except Exception as exc:
            logger.error("ada_push_failed", error=str(exc))
            return {
                "success": False,
                "error": str(exc),
                "markets_attempted": len(payload["markets"]),
            }

    # =========================================================================
    # QUALITY REPORT
    # =========================================================================

    async def get_quality_report(self) -> dict:
        """Generate a quality report for Claude oversight."""
        now = datetime.now(timezone.utc)
        cutoff_24h = now - timedelta(hours=24)
        cutoff_1h = now - timedelta(hours=1)

        async with get_session() as session:
            # Collection health
            total_markets_q = await session.execute(
                select(sql_func.count()).select_from(PredictionMarketModel)
            )
            total_markets = total_markets_q.scalar() or 0

            open_markets_q = await session.execute(
                select(sql_func.count()).select_from(PredictionMarketModel).where(
                    PredictionMarketModel.status == MarketStatus.OPEN.value
                )
            )
            open_markets = open_markets_q.scalar() or 0

            stale_q = await session.execute(
                select(sql_func.count()).select_from(PredictionMarketModel).where(
                    PredictionMarketModel.last_synced_at < cutoff_24h
                )
            )
            stale_markets = stale_q.scalar() or 0

            recently_synced_q = await session.execute(
                select(sql_func.count()).select_from(PredictionMarketModel).where(
                    PredictionMarketModel.last_synced_at >= cutoff_1h
                )
            )
            recently_synced = recently_synced_q.scalar() or 0

            # Bettor tracking health
            total_bettors_q = await session.execute(
                select(sql_func.count()).select_from(PredictionBettorModel)
            )
            total_bettors = total_bettors_q.scalar() or 0

            scored_bettors_q = await session.execute(
                select(sql_func.count()).select_from(PredictionBettorModel).where(
                    PredictionBettorModel.composite_score > 0
                )
            )
            scored_bettors = scored_bettors_q.scalar() or 0

            avg_score_q = await session.execute(
                select(sql_func.avg(PredictionBettorModel.composite_score)).where(
                    PredictionBettorModel.composite_score > 0
                )
            )
            avg_bettor_score = avg_score_q.scalar() or 0.0

            # Snapshot health
            snapshots_24h_q = await session.execute(
                select(sql_func.count()).select_from(PredictionSnapshotModel).where(
                    PredictionSnapshotModel.snapshot_at >= cutoff_24h
                )
            )
            snapshots_24h = snapshots_24h_q.scalar() or 0

        # Compute health grades
        collection_freshness = "healthy" if stale_markets < total_markets * 0.2 else "degraded"
        bettor_coverage = "healthy" if scored_bettors > 5 else "low"
        snapshot_cadence = "healthy" if snapshots_24h > 10 else "sparse"

        return {
            "collection_health": {
                "total_markets": total_markets,
                "open_markets": open_markets,
                "stale_markets": stale_markets,
                "recently_synced": recently_synced,
                "freshness_grade": collection_freshness,
            },
            "bettor_tracking": {
                "total_bettors": total_bettors,
                "scored_bettors": scored_bettors,
                "avg_composite_score": round(avg_bettor_score, 2),
                "coverage_grade": bettor_coverage,
            },
            "research_quality": {
                "note": "Research findings are ephemeral; check logs for latest run results.",
            },
            "push_health": {
                "ada_circuit_state": self._ada_breaker.state.value,
                "kalshi_circuit_state": self._kalshi_breaker.state.value,
                "polymarket_circuit_state": self._polymarket_breaker.state.value,
            },
            "snapshot_health": {
                "snapshots_24h": snapshots_24h,
                "cadence_grade": snapshot_cadence,
            },
        }

    # =========================================================================
    # STATS
    # =========================================================================

    async def get_stats(self) -> PredictionMarketStats:
        """Get aggregate statistics."""
        now = datetime.now(timezone.utc)
        cutoff_24h = now - timedelta(hours=24)

        async with get_session() as session:
            total_q = await session.execute(
                select(sql_func.count()).select_from(PredictionMarketModel)
            )
            total_markets = total_q.scalar() or 0

            open_q = await session.execute(
                select(sql_func.count()).select_from(PredictionMarketModel).where(
                    PredictionMarketModel.status == MarketStatus.OPEN.value
                )
            )
            open_markets = open_q.scalar() or 0

            kalshi_q = await session.execute(
                select(sql_func.count()).select_from(PredictionMarketModel).where(
                    PredictionMarketModel.platform == Platform.KALSHI.value
                )
            )
            kalshi_markets = kalshi_q.scalar() or 0

            poly_q = await session.execute(
                select(sql_func.count()).select_from(PredictionMarketModel).where(
                    PredictionMarketModel.platform == Platform.POLYMARKET.value
                )
            )
            polymarket_markets = poly_q.scalar() or 0

            bettors_q = await session.execute(
                select(sql_func.count()).select_from(PredictionBettorModel)
            )
            total_bettors = bettors_q.scalar() or 0

            avg_wr_q = await session.execute(
                select(sql_func.avg(PredictionBettorModel.win_rate)).where(
                    PredictionBettorModel.total_trades > 0
                )
            )
            avg_win_rate = avg_wr_q.scalar() or 0.0

            top_pnl_q = await session.execute(
                select(sql_func.max(PredictionBettorModel.pnl_total))
            )
            top_pnl = top_pnl_q.scalar() or 0.0

            volume_q = await session.execute(
                select(sql_func.sum(PredictionMarketModel.volume))
            )
            total_volume = volume_q.scalar() or 0.0

            # Last sync timestamps
            kalshi_sync_q = await session.execute(
                select(sql_func.max(PredictionMarketModel.last_synced_at)).where(
                    PredictionMarketModel.platform == Platform.KALSHI.value
                )
            )
            last_kalshi_sync = kalshi_sync_q.scalar()

            poly_sync_q = await session.execute(
                select(sql_func.max(PredictionMarketModel.last_synced_at)).where(
                    PredictionMarketModel.platform == Platform.POLYMARKET.value
                )
            )
            last_polymarket_sync = poly_sync_q.scalar()

            snap_24h_q = await session.execute(
                select(sql_func.count()).select_from(PredictionSnapshotModel).where(
                    PredictionSnapshotModel.snapshot_at >= cutoff_24h
                )
            )
            snapshots_24h = snap_24h_q.scalar() or 0

        return PredictionMarketStats(
            total_markets=total_markets,
            open_markets=open_markets,
            kalshi_markets=kalshi_markets,
            polymarket_markets=polymarket_markets,
            total_bettors_tracked=total_bettors,
            avg_bettor_win_rate=round(avg_win_rate, 4),
            top_bettor_pnl=round(top_pnl, 2),
            total_volume=round(total_volume, 2),
            last_kalshi_sync=last_kalshi_sync,
            last_polymarket_sync=last_polymarket_sync,
            last_push_to_ada=None,  # Tracked via ADA response, not stored locally
            snapshots_24h=snapshots_24h,
        )

    # =========================================================================
    # LIST / QUERY
    # =========================================================================

    async def list_markets(
        self,
        platform: Optional[str] = None,
        category: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list:
        """List markets with optional filters."""
        async with get_session() as session:
            stmt = select(PredictionMarketModel)

            if platform:
                stmt = stmt.where(PredictionMarketModel.platform == platform)
            if category:
                stmt = stmt.where(PredictionMarketModel.category == category)
            if status:
                stmt = stmt.where(PredictionMarketModel.status == status)

            stmt = stmt.order_by(PredictionMarketModel.volume.desc()).limit(limit)

            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [_market_to_pydantic(r) for r in rows]

    async def list_bettors(
        self,
        platform: Optional[str] = None,
        min_win_rate: Optional[float] = None,
        limit: int = 50,
    ) -> list:
        """List tracked bettors with optional filters."""
        async with get_session() as session:
            stmt = select(PredictionBettorModel)

            if platform:
                stmt = stmt.where(PredictionBettorModel.platform == platform)
            if min_win_rate is not None:
                stmt = stmt.where(PredictionBettorModel.win_rate >= min_win_rate)

            stmt = stmt.order_by(PredictionBettorModel.composite_score.desc()).limit(limit)

            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [_bettor_to_pydantic(r) for r in rows]

    async def get_market_snapshots(
        self,
        market_id: str,
        hours: int = 24,
    ) -> list:
        """Get price snapshots for a specific market."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        async with get_session() as session:
            stmt = (
                select(PredictionSnapshotModel)
                .where(
                    PredictionSnapshotModel.market_id == market_id,
                    PredictionSnapshotModel.snapshot_at >= cutoff,
                )
                .order_by(PredictionSnapshotModel.snapshot_at.asc())
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [_snapshot_to_pydantic(r) for r in rows]


@lru_cache()
def get_prediction_market_service() -> PredictionMarketService:
    """Get cached PredictionMarketService instance."""
    return PredictionMarketService()
