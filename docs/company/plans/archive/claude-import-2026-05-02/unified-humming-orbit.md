# Alert System Deep Review & Enhancement Plan

## Context

The alert evaluator has been silently failing because **6 out of 11 condition evaluator types referenced in the rule engine are never registered** — conditions like CSP score, contrarian score, options Greeks, sentiment, institutional flow, and earnings calendar all silently return `False` with no warning. Additionally, the reevaluation service has fragile error handling that masks failures. The user also just added the Overkill Bounce Scanner and wants to expand the alert system with more trading algorithms.

## Current State: What Exists

**Scanners/Detectors (14+):** CSP, Covered Call/PMCC, Contrarian Reversal (10-factor), Overkill Bounce (7-factor), Unusual Options, Arbitrage, Chart Scanner, Pullback Detector, Short Squeeze Detector, Momentum Decline, PEAD Detector, Elliott Wave, Dark Pool Flow, Premium Seller (12-factor)

**Alert Generators (8):** Premium, Premium Seller (10 types), Theme, Earnings (6 types), Trader Action (3 types), Learning (6 types), Research, Real-Time Orchestrator

**Condition Types Registered (26+):** Price, RSI, MACD, VIX, Volume, EMA, Support/Resistance, IV Rank, Options Greeks, Sentiment, Institutional, Portfolio, Thematic, Overkill — BUT only 5 evaluators actually work

---

## Part 1: Fix Silent Failures (Critical)

### 1.1 Register Missing Condition Evaluators

**File:** [alert_rule_engine.py](backend/services/alert_rule_engine.py)

The `__init__` only registers 5 evaluators but `_get_evaluator_for_condition()` references 11:

| Evaluator Key | Registered? | Conditions It Handles |
|--------------|-------------|----------------------|
| `price` | YES | PRICE_ABOVE/BELOW/CROSSES/CHANGE |
| `technical` | YES | RSI_*, MACD_*, EMA_* |
| `vix` | YES | VIX_*, IV_TERM_STRUCTURE, VIX_TERM_STRUCTURE |
| `volume` | YES | VOLUME_ABOVE_AVG, VOLUME_SPIKE |
| `overkill` | YES | OVERKILL_SCORE_ABOVE |
| `contrarian` | **NO** | CONTRARIAN_SCORE_ABOVE |
| `agent` | **NO** | CSP_SCORE_ABOVE, TECHNICAL_SCORE, RISK_LEVEL, MARKET_REGIME, PORTFOLIO_RISK, POSITION_*, SECTOR_CONCENTRATION |
| `options` | **NO** | DELTA_ABOVE/BELOW, DTE_BETWEEN, ANNUALIZED_RETURN_ABOVE |
| `sentiment` | **NO** | PUT_CALL_RATIO_ABOVE/BELOW, OPTIONS_VOLUME_SPIKE |
| `institutional` | **NO** | DARK_POOL_PRINT_ABOVE |
| `earnings` | **NO** | EARNINGS_WITHIN_DAYS, DIVIDEND_EX_DATE_WITHIN_DAYS |

**Action:** Create 6 new `ConditionEvaluator` subclasses and register them in `__init__`:

1. **`ContrianConditionEvaluator`** — Query `contrarian_scan_results` table for latest score (like OverkillConditionEvaluator pattern)
2. **`AgentConditionEvaluator`** — Query CSP scores from `premium_opportunities`, technical scores from chart scanner, risk/regime from market regime service, portfolio metrics from portfolio service
3. **`OptionsConditionEvaluator`** — Evaluate delta/DTE/annualized return from `premium_opportunities` or market_data dict
4. **`SentimentConditionEvaluator`** — Query put/call ratios and options volume from Tradier/unusual options scanner
5. **`InstitutionalConditionEvaluator`** — Query dark pool prints from `dark_pool_service`
6. **`EarningsConditionEvaluator`** — Check earnings calendar proximity, dividend ex-dates

### 1.2 Fix Reevaluation Service Error Handling

**File:** [alert_reevaluation_service.py](backend/services/alert_reevaluation_service.py)

| Issue | Fix |
|-------|-----|
| `process_batch_alerts()` call at :145 has no try/except | Wrap in try/except, validate return dict has expected keys |
| UPDATE count parsing at :178, :216 fragile string split | Use `RETURNING count(*)` or wrap parse in try/except with explicit logging |
| `_save_run_history()` at :261 swallows exceptions silently | Log at ERROR level (not WARNING), include traceback |
| Scheduler at scheduled_tasks.py:156 doesn't check `stats["errors"]` | Add check: if errors list non-empty, log as WARNING |

### 1.3 Add Evaluator Registration Validation

**File:** [alert_rule_engine.py](backend/services/alert_rule_engine.py)

Add a startup validation in `init_alert_rule_engine()` that logs WARNING for any ConditionType that maps to a missing evaluator. This prevents future silent failures when new condition types are added.

---

## Part 2: New Smart Rule Templates (High Value)

### 2.1 Golden Cross / Death Cross Templates

**File:** [alert_rule_engine.py](backend/services/alert_rule_engine.py) + [smart_rule_templates.py](backend/services/smart_rule_templates.py)

Add new ConditionTypes and templates:
- `SMA_GOLDEN_CROSS` — SMA(50) crosses above SMA(200)
- `SMA_DEATH_CROSS` — SMA(50) crosses below SMA(200)
- `EMA_GOLDEN_CROSS` — EMA(12) crosses above EMA(26)

These are among the most widely-used swing trading signals and are completely missing. Implement as extensions to the `TechnicalConditionEvaluator` which already handles EMA crosses — just add SMA cross logic and new templates.

### 2.2 Gap Detection Templates

Add condition types:
- `GAP_UP_PCT` — Price opens >X% above prior close
- `GAP_DOWN_PCT` — Price opens >X% below prior close

These detect gap-up/gap-down events which are key entry signals for momentum and mean reversion strategies.

### 2.3 Stochastic Oscillator Conditions

Add condition types:
- `STOCHASTIC_OVERSOLD` — %K < 20
- `STOCHASTIC_OVERBOUGHT` — %K > 80
- `STOCHASTIC_CROSS_BULLISH` — %K crosses above %D

### 2.4 ADX Trend Strength Conditions

Add condition types:
- `ADX_ABOVE` — ADX > threshold (strong trend)
- `ADX_BELOW` — ADX < threshold (choppy/ranging)

### 2.5 New Composite Templates

Using the new + existing conditions, add these high-value templates to `smart_rule_templates.py`:

| Template | Conditions | Use Case |
|----------|-----------|----------|
| `tpl_golden_cross_entry` | SMA_GOLDEN_CROSS + VOLUME_ABOVE_AVG(1.5x) + ADX_ABOVE(25) | Classic trend following entry |
| `tpl_death_cross_exit` | SMA_DEATH_CROSS + VOLUME_SPIKE(2x) | Trend reversal exit signal |
| `tpl_gap_and_go` | GAP_UP_PCT(3%) + VOLUME_SPIKE(2x) + RSI_BELOW(70) | Momentum gap continuation |
| `tpl_gap_reversal` | GAP_DOWN_PCT(-3%) + RSI_OVERSOLD + VOLUME_SPIKE(1.5x) | Mean reversion after gap down |
| `tpl_stochastic_rsi_confluence` | STOCHASTIC_OVERSOLD + RSI_OVERSOLD + SUPPORT_NEAR | Multi-indicator oversold bounce |
| `tpl_trend_breakout_confirmed` | RESISTANCE_NEAR + ADX_ABOVE(25) + VOLUME_SPIKE(2x) + MACD_ABOVE_SIGNAL | Confirmed breakout with trend strength |

---

## Part 3: New Indicator Services

### 3.1 Stochastic Oscillator Service

**New file:** `backend/services/stochastic_indicator.py`

Implement Stochastic %K/%D calculation (standard, slow, fast variants). Pattern: follow existing `supertrend_indicator.py` — pure calculation + async wrapper.

### 3.2 ADX / Directional Movement Service

**New file:** `backend/services/adx_indicator.py`

Implement ADX, DI+, DI- calculation. Critical for trend strength confirmation in breakout templates.

### 3.3 Golden/Death Cross Detection

**Enhancement to:** [TechnicalConditionEvaluator](backend/services/alert_rule_engine.py) in existing evaluator

Add SMA crossover detection using price history from Alpaca. Calculate SMA(50) and SMA(200) and detect crossover events.

---

## Part 4: Wire Scanners into Alert Hub

### 4.1 Overkill → Alert Hub Pipeline

The Overkill Bounce Scanner runs every 30 min but doesn't auto-generate alerts in the hub. Wire high-score results (>=70) into `alert_hub_service.py` as a new `OVERKILL` source.

**Files:**
- [overkill_bounce_scanner_service.py](backend/services/overkill_bounce_scanner_service.py) — Add alert generation after scan
- [alert_hub_service.py](backend/services/alert_hub_service.py) — Add OVERKILL to AlertHubSource enum if not present

### 4.2 Contrarian → Alert Hub Pipeline

Same pattern — wire contrarian scanner high-score results into alert hub.

---

## Files to Modify

| File | Changes |
|------|---------|
| `backend/services/alert_rule_engine.py` | Add 6 evaluator classes, register them, add new ConditionTypes (SMA cross, gap, stochastic, ADX), add validation |
| `backend/services/alert_reevaluation_service.py` | Fix error handling (try/except, RETURNING clause, error-level logging) |
| `backend/services/scheduled_tasks.py` | Add error checking for stats["errors"] |
| `backend/services/smart_rule_templates.py` | Add 6+ new composite templates |
| `backend/services/stochastic_indicator.py` | NEW — Stochastic oscillator service |
| `backend/services/adx_indicator.py` | NEW — ADX/DMI indicator service |
| `backend/services/overkill_bounce_scanner_service.py` | Wire scan results into alert hub |
| `backend/services/contrarian_scanner_service.py` | Wire scan results into alert hub |

---

## Verification

1. **Backend restart**: `docker restart ada-backend` then check `docker logs ada-backend --tail 30` for startup errors
2. **Rule engine init validation**: Check logs for any "missing evaluator" warnings at startup
3. **Test evaluators**: Create a test rule for each new condition type via `POST /api/rules` and execute via `POST /api/rules/{id}/execute`
4. **Reevaluation health**: Trigger manual reevaluation and verify stats dict has no errors
5. **Smart rule templates**: `GET /api/rules/templates` should show new templates
6. **Alert hub sources**: `GET /api/alert-hub/dashboard` should show OVERKILL source alerts after scan runs

---

## Priority Order

1. **Fix silent failures** (Part 1) — this is broken NOW, highest priority
2. **Register missing evaluators** (Part 1.1) — makes 20+ existing conditions actually work
3. **Golden cross + gap templates** (Part 2.1-2.2) — most requested classical patterns
4. **Wire scanners to alert hub** (Part 4) — makes existing scanners generate alerts
5. **New indicators** (Part 3) — stochastic + ADX for richer conditions
6. **Composite templates** (Part 2.5) — combine everything into powerful presets
