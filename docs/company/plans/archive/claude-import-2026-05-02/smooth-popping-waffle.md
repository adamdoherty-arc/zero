# IPO Hub Feature - Research & Implementation Plan

## Context

ADA is a theta/options-focused trading platform. Adding an IPO section provides value because:
- **Post-IPO stocks have extremely elevated IV** (80-150%+), creating rich premium-selling opportunities
- **Lock-up expirations** (180 days post-IPO) are predictable catalysts for put spreads / iron condors
- **Options become available 2-5 days after listing**, giving a narrow window to plan theta plays
- This fills a gap - ADA tracks earnings events, alerts, and scanner opportunities, but has no IPO pipeline visibility

---

## Deep Research: Where to Buy IPOs & Data Sources

### Brokerages Offering Retail IPO Access (Pre-Listing)

| Brokerage | IPO Access | Min Balance | How It Works |
|-----------|-----------|-------------|--------------|
| **Robinhood** | YES | **$0** | Submit Indication of Interest (IOI). No minimums. Best retail access. Penalizes flippers (sell within 30 days = lower future allocation) |
| **SoFi** | YES | **$0** | SoFi Invest account. Access to select IPOs. Smaller allocation pools |
| **Webull** | YES | **$20** | Must have buying power by 4PM ET day before IPO |
| **Public** | YES | **$0** | Added IPO access in 2025. Commission-free |
| **Fidelity** | YES | **~$500K** | Most restrictive. Gets biggest allocations but hard to qualify |
| **Schwab** | YES | **~$250K+** | Undisclosed minimums. Proprietary allocation algorithm |
| **Interactive Brokers** | YES | Varies | Accredited investor status for some offerings. Good for international IPOs |

**How IPO allocation works for retail:**
1. Submit Indication of Interest (IOI) for X shares at expected price range
2. Underwriter allocates (retail gets small fraction; high demand = partial fill or zero)
3. Confirmation night before / morning of IPO
4. Lock-up for flippers: some brokerages track 30-day hold behavior

**Key insight for ADA users:** Since the platform already has Robinhood integration, we can potentially surface IPO availability through the existing Robinhood API connection.

### IPO Data APIs (Ranked by Value for ADA)

#### Tier 1 - Free, Already Configured in ADA

| Source | Endpoint | Data | Free Limit | Status |
|--------|----------|------|-----------|--------|
| **Finnhub** | `GET /calendar/ipo?from=X&to=Y` | symbol, name, date, exchange, shares, price range, status (expected/priced/withdrawn/filed) | 50 req/min | `FINNHUB_API_KEY` configured, `finnhub_client.py` exists |
| **Alpha Vantage** | `GET ?function=IPO_CALENDAR` | symbol, name, ipoDate, priceRangeLow/High, currency, exchange (CSV format) | 25 req/day | `ALPHA_VANTAGE_API_KEY` configured |
| **FMP** | `GET /stable/ipos-calendar?from=X&to=Y` | symbol, company, exchange, date, priceRange, sharesOffered | 250 req/day | `FMP_API_KEY` configured, `fmp_client.py` exists |
| **FMP Prospectus** | `GET /stable/ipos-prospectus?from=X&to=Y` | public offering price, discounts, proceeds, filing dates, CIK, SEC prospectus links | Same budget | Same key |

#### Tier 2 - Available but Experimental

| Source | Endpoint | Data | Notes |
|--------|----------|------|-------|
| **Polygon** | `GET /vX/reference/ipos` | ticker, issuer, listing_date, final_price, status (pending/new/rumors/history), total_offer_size, ISIN | Experimental (`vX`), `POLYGON_API_KEY` configured |

#### Tier 3 - Free, No API Key Needed

| Source | Method | Data |
|--------|--------|------|
| **SEC EDGAR** | `edgartools` Python package | S-1 filings, lock-up terms, insider ownership %, underwriter details |
| **Nasdaq Public** | `finance-calendars` Python package | Monthly IPO data (filed/priced) - unofficial scraping |
| **MarketBeat** | Web scraping | Lock-up expiration calendar |

### IPO-Adjacent Data

| Data Type | Source | Why It Matters |
|-----------|--------|---------------|
| **Lock-up expirations** | S-1 filing (EdgarTools) or IPO date + 180 days | Primary theta catalyst - IV rises 2-3 weeks before, crushes after |
| **Options availability** | IPO date + 2-5 trading days (exchange discretion) | When CSP/CC plays become possible |
| **SPAC/De-SPAC** | spacHero.com, SPACInsider (free) | Similar elevated-IV opportunities |
| **Direct listings** | FMP/Polygon track alongside traditional IPOs | No lock-up period, all shares tradeable day 1 |
| **IPO ETFs** | `IPO` (Renaissance IPO ETF) - has options | Basket exposure to recent IPOs, tradeable options |
| **First earnings date** | ADA already tracks via earnings system | Secondary IV event post-IPO |

### Key Theta/Options Patterns Around IPOs

| Timeframe | Pattern | Theta Play |
|-----------|---------|-----------|
| Day 2-5 post-IPO | Options become available, IV 80-150%+ | Sell CSPs at support levels for massive premium |
| Weeks 1-4 | Price discovery, high IV, choppy action | Covered calls if holding, strangles/straddles for range |
| Month 1-3 | IPOs underperform, IV gradually declines | Continue premium selling as IV normalizes |
| Day 150-180 | IV rises ahead of lock-up expiration | Sell put spreads / iron condors for IV crush after expiration |
| Lock-up expiration | Avg 1-3% decline, can be 10-20% for insider-heavy | Buy back short positions after IV crush |
| First earnings | Secondary IV spike | ADA already handles earnings plays |

---

## Implementation Plan

### Phase 1: Backend - IPO Data Service

**New files:**
- [backend/services/ipo_calendar_service.py](backend/services/ipo_calendar_service.py) - Core IPO data aggregation

**Reuse existing:**
- [backend/services/finnhub_client.py](backend/services/finnhub_client.py) - Add `get_ipo_calendar()` method
- [backend/services/fmp_client.py](backend/services/fmp_client.py) - Add `get_ipo_calendar()` and `get_ipo_prospectus()` methods

**Data flow:**
```
Finnhub IPO Calendar (primary, 50 req/min)
    ↓ merge + deduplicate
FMP IPO Calendar (secondary, 250 req/day)
    ↓ enrich
FMP IPO Prospectus (SEC links, pricing details)
    ↓ calculate
Lock-up expiration dates (IPO date + 180 days)
Options availability estimate (IPO date + 3-5 trading days)
    ↓ cache
Redis (TTL: 1 hour for calendar, 24h for historical)
    ↓ store
PostgreSQL ipo_events table (historical tracking)
```

**IPO Calendar Service responsibilities:**
- Aggregate data from Finnhub + FMP (waterfall: Finnhub primary, FMP fallback)
- Calculate derived dates: lock-up expiration, estimated options availability
- Classify IPO status: `filed`, `expected`, `priced`, `trading`, `withdrawn`
- Tag theta-relevant flags: exchange (options-eligible?), estimated float, insider ownership %
- Cache aggressively (IPO calendar data changes slowly - hourly refresh is fine)

### Phase 2: Backend - Router & Endpoints

**New file:** [backend/routers/ipo_calendar.py](backend/routers/ipo_calendar.py)

**Prefix:** `/api/ipo`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/ipo/upcoming` | GET | IPOs in next N days (default 30), filtered by status/exchange |
| `/api/ipo/recent` | GET | Recently listed IPOs (last N days), with post-IPO performance |
| `/api/ipo/detail/{symbol}` | GET | Full IPO details: filing, pricing, lock-up, prospectus link |
| `/api/ipo/lockup-calendar` | GET | Upcoming lock-up expirations across all tracked IPOs |
| `/api/ipo/theta-opportunities` | GET | IPOs where options are now available + have high IV |
| `/api/ipo/sync` | POST | Manual refresh of IPO data from all sources |

**Register in:** [backend/main.py](backend/main.py) - add `app.include_router(ipo_calendar.router)`

### Phase 3: Database

**New table:** `ipo_events`

```sql
CREATE TABLE ipo_events (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    exchange VARCHAR(20),
    ipo_date DATE,
    price_range_low NUMERIC(10,2),
    price_range_high NUMERIC(10,2),
    offer_price NUMERIC(10,2),
    shares_offered BIGINT,
    total_offer_value NUMERIC(15,2),
    status VARCHAR(20) DEFAULT 'filed',  -- filed/expected/priced/trading/withdrawn
    lockup_expiration DATE,              -- calculated: ipo_date + 180 days
    options_available_est DATE,          -- calculated: ipo_date + 5 trading days
    prospectus_url TEXT,
    cik VARCHAR(20),
    insider_ownership_pct NUMERIC(5,2),
    source VARCHAR(20),                  -- finnhub/fmp/polygon/manual
    first_seen_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, ipo_date)
);

CREATE INDEX idx_ipo_events_date ON ipo_events(ipo_date);
CREATE INDEX idx_ipo_events_status ON ipo_events(status);
CREATE INDEX idx_ipo_events_lockup ON ipo_events(lockup_expiration);
CREATE INDEX idx_ipo_events_symbol ON ipo_events(symbol);
```

### Phase 4: Frontend - IPO Hub Page

**New files:**
- [frontend/src/pages/IPOHub.tsx](frontend/src/pages/IPOHub.tsx) - Main hub page
- [frontend/src/hooks/api/useIPOApi.ts](frontend/src/hooks/api/useIPOApi.ts) - React Query hooks
- [frontend/src/components/ipo/](frontend/src/components/ipo/) - Component directory

**Tabs:**
1. **Upcoming IPOs** - Calendar view of filed/expected IPOs with price ranges, dates, exchange
2. **Recently Listed** - IPOs from last 30-90 days with post-IPO performance (day 1 return, current vs offer price)
3. **Lock-Up Calendar** - Timeline of upcoming lock-up expirations with countdown, insider ownership %
4. **Theta Opportunities** - IPOs where options are available, sorted by IV rank (integrates with existing options data)

**Route:** `/ipo-hub` (lazy-loaded in [frontend/src/App.tsx](frontend/src/App.tsx))
**Sidebar:** Add to "Hubs" section in [frontend/src/components/Sidebar.tsx](frontend/src/components/Sidebar.tsx)

### Phase 5: Integration with Existing ADA Features

- **Options Hub**: Link IPO stocks to options chain analysis when options become available
- **Alert Hub**: Auto-create alerts for lock-up expiration dates (7-day and 1-day warnings)
- **Earnings Hub**: Cross-reference first earnings date for recently-IPO'd stocks
- **CSP Analysis**: Surface high-IV post-IPO stocks as CSP candidates

---

## Verification Plan

1. **Backend**: `docker restart ada-backend` then `curl http://localhost:8006/api/ipo/upcoming` - should return IPO calendar data
2. **Frontend**: Navigate to `http://localhost:5420/ipo-hub` - page loads with tabs, no console errors
3. **Data quality**: Verify Finnhub and FMP return real IPO data (not empty arrays)
4. **Lock-up dates**: Verify calculated lock-up dates are IPO date + 180 calendar days
5. **Caching**: Second request should be faster (Redis hit)

---

## Decisions (Confirmed)

- **Scope**: Full implementation (all 4 tabs)
- **SPACs**: Not included - IPOs and direct listings only. SPACs can be added later.
- **Lock-up alerts**: Manual opt-in only - show a "Create Alert" button in the Lock-Up Calendar tab that creates an alert in Alert Hub when clicked
