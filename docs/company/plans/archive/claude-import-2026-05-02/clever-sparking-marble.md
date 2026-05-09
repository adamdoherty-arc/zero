# Overkill Bounce Scanner - Implementation Plan

## Context

**What**: Build a scanner that mimics [Overkill Trading's](https://www.tiktok.com/@overkilltrading) approach to finding low-priced stocks primed for bounce plays. Overkill Trading uses an EMA(9/21/100) + MACD(9,21,21) system to identify high-quality pullback entries in trending stocks - filtering for "B" (Buy) signals where trend + momentum align, while avoiding "X mo" (no momentum) and "x corr" (correction) setups.

**Why**: The user wants ADA to automatically identify the same kind of setups Overkill Trading shares on TikTok/Discord - stocks that are low, showing signs of reversal, with clean EMA structure for entry.

**Outcome**: A new `/api/scanner/overkill` endpoint suite that scores stocks on a 7-factor system, classifies them into signal types (BUY / REVERSAL_SETUP / CORRECTION_WATCH), runs every 30min during market hours, and shows results in a new tab on the Strategy Scanner Hub page.

---

## User Preferences
- **Price range**: $1 - $50 (wider net, not just penny stocks)
- **Scheduling**: Auto-scan every 30min during market hours + manual trigger
- **Frontend**: New tab in existing Strategy Scanner Hub (`/strategy-hub`)

---

## Scoring System (0-100)

| # | Factor | Weight | What it Measures |
|---|--------|--------|-----------------|
| 1 | EMA Stack Alignment | 25% | EMA(9) > EMA(21) > EMA(50) > EMA(100) ordering + price in pullback zone near EMA 21/50 |
| 2 | MACD Momentum | 20% | MACD(9,21,21) line vs signal, histogram turning positive |
| 3 | Volume Confirmation | 15% | Volume surge on bounce candles (2-3x avg = ideal) |
| 4 | Price Structure | 15% | Support/resistance quality, consolidation, ATR-normalized |
| 5 | RSI Position | 10% | RSI(14) in 25-40 "bounce zone" showing reversal |
| 6 | Proximity to Low | 10% | Distance from 52-week low (1-15% above = sweet spot) |
| 7 | Mean Reversion | 5% | BB position, distance below SMA(200) |

### Signal Classification

| Signal | Criteria | Action |
|--------|----------|--------|
| **BUY** | Score >= 70, price in EMA(21-50) zone, MACD bullish | Alert immediately |
| **REVERSAL_SETUP** | Score >= 60, near 52w low, EMA(9) crossing EMA(21) | Watch closely |
| **CORRECTION_WATCH** | Score >= 50, price at/below EMA(100), waiting for bounce | Monitor |
| **NO_SIGNAL** | Below thresholds | Skip |

---

## Implementation Steps

### Step 1: Database Migration
**Create**: `backend/alembic/versions/YYYYMMDD_overkill_bounce_scanner.py`

Table `overkill_scan_results` with columns for: symbol, composite_score, grade, signal_type, price, all 4 EMAs, ema_stack_bullish flag, RSI, MACD (line/signal/histogram/bullish flag), 52-week high/low/pct_off_low, volume/avg_volume/ratio, all 7 factor scores (0.0-1.0), suggested entry/stop/target/risk-reward, scanned_at, is_active, expires_at.

Indexes on: (composite_score DESC WHERE is_active), (symbol, scanned_at DESC), (signal_type WHERE is_active), (is_active, scanned_at DESC).

### Step 2: Scanner Service
**Create**: `backend/services/overkill_bounce_scanner_service.py` (~800-1000 lines)

Key structure:
- `OverkillBounceResult` dataclass with all scored fields
- `OverkillBounceScannerService` class with singleton `get_overkill_scanner_service()`
- 7 factor methods: `_factor_ema_stack()`, `_factor_macd_momentum()`, `_factor_volume_confirmation()`, `_factor_price_structure()`, `_factor_rsi_position()`, `_factor_proximity_low()`, `_factor_mean_reversion()`
- `_classify_signal()` - signal type based on score + factor values
- `_calculate_trade_levels()` - entry (2% below current), stop (below support or 2x ATR), target (next resistance or 15-30% up)
- `_prefetch_market_data()` - batch fetch 120+ days from Alpaca for EMA(100)
- `_persist_results()` / `_deactivate_old_scans()` - DB storage
- Cache via Redis (5min TTL)

**Reuse from** `backend/services/contrarian_scanner_service.py`:
- Pure-math helpers: `_compute_rsi()`, `_compute_ema()`, `_compute_macd()`, `_compute_sma()`, `_compute_bollinger_bands()`, `_compute_atr()`
- Lazy semaphore pattern for API concurrency (max 3)
- Score-to-grade mapping
- DB persistence pattern

**Default universe filter**: $1-$50 price, avg volume >= 500K, from universe_service or stock_universe table.

### Step 3: Router
**Create**: `backend/routers/overkill_bounce_scanner.py` (~200 lines)
**Prefix**: `/api/scanner/overkill`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/scan` | Run scan with filters (symbols, min_score, max_price, min_volume, signal_types) |
| GET | `/top` | Cached top opportunities (default: score >= 60, limit 25) |
| GET | `/{symbol}/detail` | Full 7-factor breakdown for one symbol |
| GET | `/{symbol}/history` | Historical scan scores |
| GET | `/signals/{signal_type}` | Filter by BUY / REVERSAL_SETUP / CORRECTION_WATCH |

### Step 4: Wire into Backend
**Modify**: `backend/main.py` - Import and register router with `app.include_router()`

### Step 5: Scheduled Scanning
**Modify**: `backend/services/scheduled_tasks.py` (or equivalent scheduler)

Add a task that runs every 30 minutes during market hours (9:30 AM - 4:00 PM ET):
- Fetch default universe (filtered by price/volume)
- Run full scan
- Persist results
- Log summary (X symbols scanned, Y BUY signals, Z REVERSAL_SETUP)

### Step 6: Alert Integration
**Modify**: `backend/services/alert_rule_engine.py`

Add condition type `overkill_score_above` so users can create rules like: "Alert me when any stock gets an Overkill BUY signal with score >= 80"

### Step 7: Frontend Tab
**Modify**: `frontend/src/pages/StrategyScannerHub.tsx`

Add `'overkill'` to the `ScannerTab` type union and `VALID_TABS` array. Add a tab button with a bolt/rocket icon. Add conditional render block for the `OverkillBounceTab` component.

**Create**: `frontend/src/components/scanner/OverkillBounceTab.tsx` (~300 lines)

Tab contents:
- **Top bar**: Manual scan trigger button + last scanned timestamp + signal type filter chips (BUY / REVERSAL / CORRECTION / ALL)
- **Results table**: Symbol, Price, Score, Grade, Signal Type, EMA Stack status, MACD status, Volume Ratio, Suggested Entry/Stop/Target, R:R ratio
- **Expandable row detail**: 7-factor breakdown bars showing each factor's score contribution
- Color coding: BUY = green, REVERSAL_SETUP = yellow, CORRECTION_WATCH = orange

**Create**: `frontend/src/hooks/useOverkillScanner.ts` (~60 lines)

React Query hooks:
- `useOverkillTop()` - GET `/scanner/overkill/top` (auto-refetch 5min)
- `useOverkillScan()` - POST `/scanner/overkill/scan` (mutation)
- `useOverkillDetail(symbol)` - GET `/scanner/overkill/{symbol}/detail`
- `useOverkillSignals(signalType)` - GET `/scanner/overkill/signals/{type}`

---

## Note on OCR / Chart Vision

ADA does **not** need OCR to replicate this - all the data (price, volume, EMAs, MACD) is computed mathematically from raw market data via Alpaca. Chart vision (`chart_vision_analyzer.py`) could optionally validate top signals by visually confirming the pullback pattern, but it's a nice-to-have, not a requirement. The scanner works entirely on numerical data.

---

## Files Summary

| Action | File | Purpose |
|--------|------|---------|
| **Create** | `backend/alembic/versions/YYYYMMDD_overkill_bounce_scanner.py` | DB table + indexes |
| **Create** | `backend/services/overkill_bounce_scanner_service.py` | Core 7-factor scoring engine |
| **Create** | `backend/routers/overkill_bounce_scanner.py` | API endpoints |
| **Create** | `frontend/src/components/scanner/OverkillBounceTab.tsx` | Scanner tab UI |
| **Create** | `frontend/src/hooks/useOverkillScanner.ts` | React Query hooks |
| **Modify** | `backend/main.py` | Register router |
| **Modify** | `backend/services/scheduled_tasks.py` | 30min auto-scan |
| **Modify** | `backend/services/alert_rule_engine.py` | `overkill_score_above` condition |
| **Modify** | `frontend/src/pages/StrategyScannerHub.tsx` | Add overkill tab |

---

## Verification

1. **Backend startup**: `docker restart ada-backend` + `docker logs ada-backend --tail 30` - no import errors
2. **Scan endpoint**: `curl -X POST http://localhost:8006/api/scanner/overkill/scan -H "Content-Type: application/json" -d '{"symbols": ["SOFI","PLTR","NIO","LCID","RIVN","HOOD","MARA","RIOT","COIN","SNAP"]}'` - returns scored results with signal types
3. **Top endpoint**: `curl http://localhost:8006/api/scanner/overkill/top` - returns cached top opportunities
4. **Detail endpoint**: `curl http://localhost:8006/api/scanner/overkill/SOFI/detail` - shows all 7 factor scores
5. **DB verification**: Confirm `overkill_scan_results` table has rows with scores, grades, and signals
6. **Frontend**: Navigate to `/strategy-hub`, click "Overkill" tab, verify results table renders with data
7. **Scheduler**: Check logs for 30min scan executions during market hours
