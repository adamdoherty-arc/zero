# Portfolio Deep Scan: Comprehensive Technical Indicators for All Positions

## Context

**Problem**: The "Scan Positions" button currently runs only 2 of 23+ available scanners (Overkill 7-factor + Contrarian 10-factor). It shows "0 Overkill + 0 Contrarian alerts" when no positions hit the alert thresholds (>=70 and >=65 respectively), giving the impression nothing was analyzed. Meanwhile, the platform has 40+ technical indicators across 25+ service files that are completely disconnected from the portfolio scanning flow. Kronos price forecasts exist but aren't part of the scan. There's no way to see a comprehensive technical breakdown of each held position.

**Outcome**: A new "Deep Scan" feature that runs ALL available indicators on every held position and displays a rich, expandable technical analysis panel per stock row -- including Kronos forecasts, momentum, trend, volatility, volume, patterns, options flow, and a composite score.

---

## Architecture Overview

```
[Deep Scan Button] --> POST /api/portfolio/deep-scan
                           |
                    PositionDeepScanService
                           |
          +--------+-------+-------+--------+
          |        |       |       |        |
       Fetch    Kronos   Signal  MTF     DB Queries
       OHLCV   Predict   Engine  Conf   (options, IV)
       (once)    |         |       |        |
          |      |         |       |        |
     Pure-math   |         |       |        |
     indicators  |         |       |        |
     (parallel)  |         |       |        |
          |      |         |       |        |
          +------+---------+------+---------+
                           |
                  SymbolDeepScanResult (per stock)
                           |
                  Composite Score + Direction
                           |
                  Redis Cache (5-min TTL)
                           |
                  [Expandable Row Panel in UI]
```

---

## Phase 1: Backend Service (`backend/services/position_deep_scan_service.py`)

**New file** ~400 lines. Orchestrates all indicators with shared OHLCV fetch.

### Key Design: Fetch OHLCV Once, Compute Everything

All 15+ math-based indicators consume the same OHLCV data. Current system fetches independently per indicator per symbol. Deep scan fetches once and passes arrays to all:

```
OHLCV fetch (1x per symbol, semaphore=3)
    |
    +--> Momentum: RSI, MACD, Stochastic, ADX, WaveTrend, TDI
    +--> Trend: SuperTrend, EMA stack (9/21/50/100/200), Regression Channel
    +--> Volatility: Squeeze Momentum, Bollinger Bands, ATR, Williams VIX Fix
    +--> Volume: Volume ratio, OBV trend, Volume Profile (POC/VAH/VAL)
    +--> Patterns: Divergences (RSI/MACD/OBV), Chart patterns, SMC zones
```

### External Async Calls (parallel, separate from OHLCV math)

| Call | Service | Semaphore | Est. Time |
|------|---------|-----------|-----------|
| Kronos forecasts | `kronos_service.predict_price()` | Kronos sem(2) | ~2-5s/symbol |
| Signal Engine | `signal_engine.generate_signal()` | Own data fetch | ~1s/symbol |
| MTF Confluence | `confluence_scorer.analyze()` | Fetches 4 TFs | ~2s/symbol |
| Quant Signals | `quant_signals_service.generate_signals()` | FactorScoring | ~1s/symbol |
| Options flow | DB query `options_flow_analysis` | None | ~200ms batch |
| IV Analysis | DB + Tradier | API sem | ~1s/symbol |

### Composite Score (0-100)

Weighted aggregation of all indicator signals normalized to -1.0 (bearish) to +1.0 (bullish):

| Source | Weight | Normalization |
|--------|--------|---------------|
| Signal Engine confluence | 15% | Score/100 mapped to [-1, 1] |
| Overkill scanner | 10% | Score/100 mapped to [-1, 1] |
| Contrarian scanner | 10% | Score/100 mapped to [-1, 1] |
| Momentum group (RSI+MACD+Stoch+ADX) | 15% | Consensus vote |
| Trend group (SuperTrend+EMA stack) | 10% | Direction consensus |
| Kronos forecast | 10% | Direction + confidence |
| MTF Confluence | 10% | Score/100 mapped to [-1, 1] |
| Squeeze momentum | 5% | Direction + momentum value |
| Volume confirmation | 5% | Surge + OBV trend |
| Quant factor model | 5% | Score/100 mapped to [-1, 1] |
| Options flow | 5% | P/C ratio + unusual activity |

Final: `composite = 50 + (weighted_sum * 50)` clipped to [0, 100]

### Error Tolerance

Every indicator wrapped in try/except. Failures:
- Return `None` for that indicator's fields
- Add to `errors: list[str]` on the result
- Never block other indicators
- Log at warning level with structlog

### Caching

Redis key: `deep_scan:{sorted_symbols_hash}`, TTL=300s (5 min, matching Kronos and Overkill patterns).

### Performance Estimate (6 positions)

| Phase | Time | Notes |
|-------|------|-------|
| OHLCV fetch | ~1.0s | 6 symbols, sem=3, 2 waves |
| CPU indicators | ~0.3s | All pure math, parallel per symbol |
| Kronos | ~4-10s | GPU inference, sem=2, 3 waves |
| Signal Engine + MTF + Quant | ~3s | Async with sem=3 |
| DB queries | ~0.2s | Batched with ANY() |
| **Total** | **~8-15s** | First scan; cached = instant |

### Reused Services & Functions

| Indicator | Import From | Function |
|-----------|-------------|----------|
| RSI (Wilder) | `signal_engine.py` pattern (line 229) | Inline calculation |
| MACD | `signal_engine.py` pattern (line 268) | Inline calculation |
| SuperTrend | `backend/services/supertrend_indicator.py` | `calculate_supertrend()` |
| Stochastic | `backend/services/stochastic_indicator.py` | `calculate_stochastic()` |
| ADX | `backend/services/adx_indicator.py` | `calculate_adx()` |
| WaveTrend | `backend/services/wavetrend_indicator.py` | `calculate_wavetrend()` |
| TDI | `backend/services/tdi_indicator.py` | `calculate_tdi()` |
| Squeeze | `backend/services/squeeze_momentum.py` | `calculate_squeeze_momentum()` |
| Bollinger | `signal_engine.py` pattern (line 295) | Inline calculation |
| ATR | `signal_engine.py` pattern (line 309) | Inline calculation |
| Williams VIX Fix | `backend/services/williams_vix_fix.py` | `calculate_williams_vix_fix()` |
| Divergences | `backend/services/divergence_detector.py` | `calculate_all_divergences()` |
| Patterns | `backend/services/pattern_recognition.py` | `get_pattern_analysis()` |
| SMC Zones | `backend/services/smc_zones_service.py` | `get_smc_zones()` |
| Volume Profile | `src/volume_profile_analyzer.py` | `VolumeProfileAnalyzer.calculate_volume_profile()` |
| Regression Channel | `backend/services/regression_channel.py` | `calculate_regression_channel()` |
| Kronos | `backend/services/kronos/kronos_service.py` | `predict_price()` |
| Signal Engine | `backend/services/signal_engine.py` | `generate_signal()` |
| MTF Confluence | `backend/services/multi_timeframe_confluence.py` | `ConfluenceScorer.analyze()` |
| Quant Signals | `backend/services/quantitative_signals_service.py` | `generate_signals()` |
| Options Flow | DB table `options_flow_analysis` | SQL query with ANY() |
| IV Analysis | `backend/services/iv_analysis.py` | `calculate_iv_analysis()` |
| EMA Stack | Overkill pattern (line ~200) | Inline numpy EMA |
| OBV | `backend/services/divergence_detector.py` | `calculate_obv()` |

---

## Phase 2: Backend Endpoint (`backend/routers/portfolio_intelligence.py`)

**Modify existing file** ~60 lines added.

### New Endpoint

```
POST /api/portfolio/deep-scan
Body: { symbols?: string[], categories?: string[] }
Response: DeepScanResponse { status, results: {symbol: SymbolDeepScanResult}, duration_ms, cached }
```

- Reuses existing `_fetch_held_symbols()` (line 89) for default symbol list
- 300s timeout via `asyncio.wait_for`
- Cache check first, store after computation
- Categories filter: `["momentum", "trend", "volatility", "volume", "patterns", "forecast", "options", "quant", "scanners", "mtf"]` -- `None` means all

### Response Models

Add Pydantic models for all indicator category groups (MomentumIndicators, TrendIndicators, VolatilityIndicators, VolumeIndicators, PatternData, ForecastData, SignalEngineData, OptionsFlowData, QuantData, MTFConfluenceData) plus the top-level `SymbolDeepScanResult` and `DeepScanResponse`.

---

## Phase 3: Frontend Hook (`frontend/src/hooks/usePositionDeepScan.ts`)

**New file** ~100 lines.

- TypeScript interfaces mirroring all Pydantic models
- `useDeepScanPositions()` -- React Query `useMutation` calling `POST /portfolio/deep-scan`
- Helper functions: `getIndicatorColor(value, thresholds)`, `formatIndicatorValue()`, `getDirectionIcon()`
- Invalidates `['portfolio', 'positions-intelligence']` on success

---

## Phase 4: Frontend Panel (`frontend/src/components/portfolio/PositionDeepScanPanel.tsx`)

**New file** ~350 lines. Expandable panel rendered below each position row.

### Layout (per stock)

```
+------------------------------------------------------------------+
| ASTX Deep Scan  |  Composite: 42 NEUTRAL  |  8 Bull / 6 Bear / 9 Neutral
+------------------------------------------------------------------+
| MOMENTUM                                                          |
|  RSI 38 ●  MACD ▼ Bear Cross  Stoch 25/31 ↗  ADX 22 Weak       |
|  WaveTrend -45 Neutral  TDI Neutral                              |
+------------------------------------------------------------------+
| TREND                                                             |
|  SuperTrend ↑ BUY  EMA Stack: Mixed (9<21, 50<100<200)          |
|  Regression: ↓ R²=0.72                                           |
+------------------------------------------------------------------+
| VOLATILITY                                                        |
|  Squeeze: OFF  BB Position: 35%  ATR: 2.1% ($1.02)              |
|  IV Rank: 65  IV %ile: 72  HV20: 48%  WVF: Neutral              |
+------------------------------------------------------------------+
| VOLUME                                                            |
|  Vol Ratio: 0.8x avg  OBV: ↓ Declining  POC: $47.50 (above)    |
+------------------------------------------------------------------+
| FORECAST (Kronos)                                                 |
|  Direction: ▲ Bullish +2.3%  Confidence: 78%  Vol: 3.1%         |
+------------------------------------------------------------------+
| PATTERNS                                                          |
|  Divergence: Hidden Bull (RSI) ●  No chart patterns detected     |
|  SMC: Order Block @ $46.20 (demand)  FVG @ $47.80               |
+------------------------------------------------------------------+
| OPTIONS FLOW                                                      |
|  Max Pain: $48  P/C Ratio: 0.72  Unusual: 2 sweeps              |
+------------------------------------------------------------------+
| SIGNAL ENGINE                                                     |
|  Direction: LONG  Confluence: 62/100  Entry: $46.50  SL: $44.80 |
+------------------------------------------------------------------+
| QUANT FACTORS                                                     |
|  Score: 58 HOLD  Mom: High  Val: Med  Quality: Low              |
+------------------------------------------------------------------+
| MTF CONFLUENCE                                                    |
|  Score: 55  Direction: Neutral  3/4 timeframes agree             |
+------------------------------------------------------------------+
```

### Design Details
- Each section is a collapsible card (default: all expanded on first load)
- Indicator values use color-coded badges matching existing scoreChipColor pattern
- Green shades = bullish, Red shades = bearish, Slate = neutral, Amber = caution
- Loading skeleton shown during scan
- Error indicators for failed sections (yellow warning icon + "unavailable" text)
- Composite score uses a horizontal gauge/progress bar with gradient

---

## Phase 5: Wire Into Table (`frontend/src/components/portfolio/StocksWithCCTable.tsx`)

**Modify existing file** ~40 lines added.

1. Add "Deep Scan" button next to existing "Scan Positions" button (styled with Activity icon, cyan accent to differentiate)
2. Add `expandedSymbol` state and `deepScanData` from mutation result
3. After each position `<tr>`, render conditional expanded `<tr>` with `<PositionDeepScanPanel>` spanning all columns
4. Click on a row toggles expansion (shows that symbol's deep scan results)
5. If deep scan hasn't run yet, show "Run Deep Scan first" prompt in expanded area

---

## Phase 6: Enhance Signals Column (`frontend/src/components/portfolio/PositionSignalsCell.tsx`)

**Modify existing file** ~20 lines added.

- Accept optional `compositeScore` and `compositeDirection` props
- When available, show a new badge: `DS 72 ▲` (Deep Scan composite score + direction arrow)
- Badge color follows same green/amber/slate pattern

---

## Files Modified/Created Summary

| File | Action | Est. Lines |
|------|--------|------------|
| `backend/services/position_deep_scan_service.py` | **CREATE** | ~400 |
| `backend/routers/portfolio_intelligence.py` | MODIFY | +60 |
| `frontend/src/hooks/usePositionDeepScan.ts` | **CREATE** | ~100 |
| `frontend/src/components/portfolio/PositionDeepScanPanel.tsx` | **CREATE** | ~350 |
| `frontend/src/components/portfolio/StocksWithCCTable.tsx` | MODIFY | +40 |
| `frontend/src/components/portfolio/PositionSignalsCell.tsx` | MODIFY | +20 |

---

## Verification Plan

1. **Backend endpoint**: `docker restart ada-backend`, then `curl -X POST http://localhost:8006/api/portfolio/deep-scan | jq .` -- verify all indicator categories populated, composite score calculated, no crash
2. **Cache**: Run same curl twice -- second should show `cached: true` and be instant
3. **Error tolerance**: Temporarily break one indicator import, verify partial results still returned with error logged
4. **Frontend**: Navigate to `http://localhost:5420/portfolio`, click "Deep Scan", verify progress indicator, then expandable rows with indicator data
5. **Smoke test**: `python .claude/skills/playwright-testing/runner.py smoke http://localhost:5420/portfolio`
