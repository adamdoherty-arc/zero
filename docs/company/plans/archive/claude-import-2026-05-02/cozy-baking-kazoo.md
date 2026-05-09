# Plan: Unified Daily Trading Plan — Aggregate All Scanners

## Context

The Trade Planner shows "0 recommendations" because the `DailyPlannerService` only pulls from two DB tables: `discord_trading_signals` (XTrades) and `premium_opportunities` (CSP scanner). Two other scanners run on schedules and write to their own tables but are **completely disconnected** from the Trade Planner:

- **Overkill Bounce Scanner** — runs every 30 min, writes to `overkill_scan_results` (bounce plays $1-$50)
- **Position Opportunities** — runs every 15 min, writes to `position_opportunities` (covered calls on held positions, CSP alternatives, CC rolls)

The user needs a single daily plan that aggregates ALL opportunity sources and categorizes them (CSPs to sell, covered calls on positions, bounce plays to watch, XTrades signals).

## Approach: Extend DailyPlannerService (not LangGraph)

The LangGraph recommendation graph is too slow (60s timeout, on-demand CSP scan). The `DailyPlannerService` already reads from pre-populated DB tables — it just needs to read from two more. This is minimal, low-risk, and follows existing patterns.

---

## Phase 1: Backend — Add Overkill + Position Opportunities Sources

### 1.1 Add enum values to `RecommendationSource`
**File:** [daily_planner_service.py](backend/services/daily_planner_service.py) (line 35)

```python
OVERKILL = "overkill"
POSITION_OPP = "position_opportunity"
```

### 1.2 Add `category` field to `DailyRecommendation` dataclass
**File:** [daily_planner_service.py](backend/services/daily_planner_service.py) (line 44)

Add after `annualized_return`:
```python
category: str = "opportunity"  # csp, covered_call, bounce_play, signal, position_action
```

Set categories on existing recs in `_fetch_relevant_alerts()`:
- XTrades recs (line 439): `category="signal"`
- CSP recs (line 503): `category="csp"`

### 1.3 Add `_fetch_overkill_opportunities()` method
New async method querying `overkill_scan_results`:

```sql
SELECT symbol, composite_score, grade, signal_type,
       price, ema_stack_bullish, rsi_14, macd_bullish, volume_ratio,
       suggested_entry, suggested_stop, suggested_target, risk_reward_ratio
FROM overkill_scan_results
WHERE is_active = TRUE AND composite_score >= 50
  AND signal_type IN ('BUY', 'REVERSAL_SETUP')
ORDER BY composite_score DESC
LIMIT 10
```

Convert to `DailyRecommendation` with:
- `strategy`: "bounce_buy" or "reversal_setup"
- `category`: "bounce_play"
- `source`: `RecommendationSource.OVERKILL`
- `score`: `composite_score` (already 0-100)
- `reasoning`: Include grade, signal type, RSI, volume ratio, risk/reward
- Map `suggested_entry/stop/target` to `entry_price/stop_price/target_price`
- Map `price` to `stock_price`

### 1.4 Add `_fetch_position_opportunities()` method
New async method querying `position_opportunities`:

```sql
SELECT position_symbol, position_type, opportunity_type, option_type,
       strike, expiration, dte, premium, premium_pct, annualized_return,
       underlying_price, delta, theta, iv, overall_score,
       probability_of_profit, confidence_level, key_factors, risk_factors
FROM position_opportunities
WHERE overall_score >= 40 AND expires_at > NOW()
ORDER BY overall_score DESC
LIMIT 15
```

Convert to `DailyRecommendation` with:
- `strategy`: Map opportunity_type — `stock_cc` -> "covered_call", `cc_roll` -> "cc_roll", `cc_new` -> "covered_call", `csp_alternative` -> "csp_alternative"
- `category`: "covered_call" for CC types, "csp" for CSP alternatives
- `source`: `RecommendationSource.POSITION_OPP`
- Populate `strike`, `expiration`, `dte`, `premium`, `premium_pct`, `annualized_return`, `delta`, `theta`
- `reasoning`: Include opportunity type, strike, DTE, annualized return, key factors

### 1.5 Wire into `get_daily_plan()` asyncio.gather
**File:** [daily_planner_service.py](backend/services/daily_planner_service.py) (line 241)

Add two more tasks:
```python
results = await asyncio.gather(
    self._fetch_portfolio_snapshot(target_date),
    self._fetch_relevant_alerts(target_date),
    self._fetch_learning_recommendations(target_date),
    self._fetch_events(target_date),
    self._fetch_day_of_week_stats(target_date.weekday()),
    self._fetch_planned_trades(target_date),
    self._fetch_overkill_opportunities(),        # NEW [6]
    self._fetch_position_opportunities(),         # NEW [7]
    return_exceptions=True
)
```

Unpack `results[6]` and `results[7]` with exception handling (same pattern as existing).

### 1.6 Extend `_merge_recommendations()` signature
**File:** [daily_planner_service.py](backend/services/daily_planner_service.py) (line 722)

```python
async def _merge_recommendations(
    self,
    alerts: list[DailyRecommendation],
    learning: list[DailyRecommendation],
    overkill: list[DailyRecommendation],      # NEW
    position_opps: list[DailyRecommendation],  # NEW
) -> list[DailyRecommendation]:
```

Change line 738: `for rec in alerts + learning + overkill + position_opps:`

### 1.7 Increase recommendation limit from 10 to 20
**File:** [daily_planner_service.py](backend/services/daily_planner_service.py) (line 817)

Change `sorted_recs[:10]` to `sorted_recs[:20]` to accommodate additional sources.

---

## Phase 2: API Response — Add `category` Field

### 2.1 Add `category` to `RecommendationResponse`
**File:** [daily_planner.py](backend/routers/daily_planner.py) (line 30)

Add: `category: str = "opportunity"`

### 2.2 Wire `category` in response conversion
**File:** [daily_planner.py](backend/routers/daily_planner.py)

Find the `_convert_daily_plan()` or inline conversion and add `category=r.category`.

---

## Phase 3: Frontend — Categorized Display

### 3.1 Add `category` to TypeScript interfaces
**Files:**
- [DayDashboard.tsx](frontend/src/components/planner/DayDashboard.tsx) — recommendation interface
- [useTodayCommandCenter.ts](frontend/src/hooks/useTodayCommandCenter.ts) — if it has its own type

Add `category?: string` to the recommendation type.

### 3.2 Group recommendations by category in DayDashboard
**File:** [DayDashboard.tsx](frontend/src/components/planner/DayDashboard.tsx) (line 633-679)

Replace the flat grid with category-grouped sections:

```
- "Cash-Secured Puts" (category === 'csp') — blue accent
- "Covered Calls on Your Positions" (category === 'covered_call') — green accent  
- "Bounce Plays to Watch" (category === 'bounce_play') — orange accent
- "XTrades Signals" (category === 'signal') — purple accent
```

Each section: header with count, then grid of `UnifiedAlertTile`. Hide empty sections.

### 3.3 Add category badge to UnifiedAlertTile
**File:** [UnifiedAlertTile.tsx](frontend/src/components/shared/UnifiedAlertTile.tsx)

Small colored chip showing category type (CSP / CC / Bounce / Signal).

### 3.4 Update empty state messaging
**File:** [DayDashboard.tsx](frontend/src/components/planner/DayDashboard.tsx) (line 654-679)

Change "No recommendations for today" to be more specific about what was checked, and change "Run Scanner" button to trigger a refresh rather than linking away to Alert Hub.

---

## Files Modified Summary

| File | Changes |
|------|---------|
| `backend/services/daily_planner_service.py` | +2 enum values, +1 dataclass field, +2 fetch methods, extend gather + merge, raise limit |
| `backend/routers/daily_planner.py` | +1 response field, wire category |
| `frontend/src/components/planner/DayDashboard.tsx` | Category-grouped display, updated empty state |
| `frontend/src/components/shared/UnifiedAlertTile.tsx` | Category badge |

## Verification

1. **Backend**: `docker restart ada-backend` then `curl http://localhost:8006/api/planner/day/2026-04-21` — verify response includes recommendations from multiple sources with category field
2. **Database check**: Verify `overkill_scan_results` and `position_opportunities` tables have data: 
   - `docker exec ada-postgres psql -U ada -c "SELECT COUNT(*) FROM overkill_scan_results WHERE is_active = TRUE"`
   - `docker exec ada-postgres psql -U ada -c "SELECT COUNT(*) FROM position_opportunities WHERE expires_at > NOW()"`
3. **Frontend**: Browse to `http://localhost:5420/trade-planner` — verify categorized recommendations appear
4. **Edge cases**: If both tables are empty, existing XTrades + CSP flow still works (graceful degradation)
