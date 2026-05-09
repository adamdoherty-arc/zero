# Covered Call Scanner Overhaul — Accurate Premiums + 3-Column Friday Layout

## Context

The user primarily trades **covered calls** now and has two blockers with the current scanner:

1. **Premiums shown are "way off" from reality.** Investigation found the root causes: the `_evaluate_covered_call()` logic at [strategy_evaluator.py:445-446](backend/services/options_hub/strategy_evaluator.py#L445-L446) uses the **mid price** `(bid + ask) / 2` — but a covered call seller only receives the **bid** on execution. On wide-spread / illiquid contracts that overstates premium 5–50%. Compounding this: 2–5 min stale cache with no freshness indicator, no liquidity filter, and no on-demand refresh.

2. **No easy "Friday-at-a-glance" layout for CCs.** The user wants 3 columns per symbol: `Friday 1 | Friday 2 | Monthly-only`. Stocks with weekly options fill columns 1 and 2. Stocks that only trade monthly-cycle options (no weeklies) put their sole expiration in column 3. This makes it instant to scan and sort by premium yield without mixing apples-to-oranges DTEs.

3. **Covered calls on already-owned stock** need to keep their own clearly-labeled section (stays in Portfolio › Opportunities tab) and get the same accuracy + layout upgrades.

## Desired Outcome

- One sortable CC view in **Main Scanner › Covered Calls tab** and **Portfolio › Opportunities tab** where the CC toggle is active.
- Three fixed expiration columns: `Fri 1`, `Fri 2`, `Monthly-only` (populated per rules below).
- Each cell shows a premium you can actually get filled at (bid, not mid), filtered for liquidity, with an age indicator and a per-row live-refresh button.

---

## Architecture Decisions

### Backend: reuse the consolidated-premiums pipeline, do NOT rebuild Margin CC

The dynamic-column infrastructure **already exists** at [scanner.py:3348-3639](backend/routers/scanner.py#L3348-L3639) (`GET /api/scanner/consolidated-premiums`). It already:
- Filters Friday-only expirations via `EXTRACT(DOW FROM expiration) = 5` ([scanner.py:3178](backend/routers/scanner.py#L3178), [scanner.py:3373](backend/routers/scanner.py#L3373))
- Supports `option_type=CALL` to return covered-call premiums
- Ranks expirations per-symbol via `DENSE_RANK() OVER (PARTITION BY symbol ...)` and emits `expiration_columns` keyed by both date and `rank_N` ([scanner.py:3496](backend/routers/scanner.py#L3496), [scanner.py:3626-3629](backend/routers/scanner.py#L3626-L3629))

The portfolio variant at `/api/portfolio/position-premiums-grid` uses the same response shape. So **we extend scanner.py**, not replace it. The existing `Margin CC tab` (fixed-13-col layout at [CoveredCallsTab.tsx](frontend/src/components/scanner/CoveredCallsTab.tsx)) will be **replaced by the `ConsolidatedPremiumsTable` rendered with `optionType="CALL"` and the new 3-column logic.

### Frontend: reuse `ConsolidatedPremiumsTable`, add a classifier

[ConsolidatedPremiumsTable.tsx](frontend/src/components/options/ConsolidatedPremiumsTable.tsx) already renders `N` dynamic columns from `expiration_dates.columns`. We change it to **always render exactly 3 columns** (`Fri 1`, `Fri 2`, `Monthly`) and look up each row's cell using a small classifier against the row's `expiration_columns` dict.

---

## Implementation Plan

### Phase A — Premium Accuracy (fixes the "way off" problem)

**File 1: [backend/services/options_hub/strategy_evaluator.py](backend/services/options_hub/strategy_evaluator.py)**

- **Line 445-446** `_evaluate_covered_call`: change
  ```
  premium = option_data.get("mid", 0) or ((bid + ask) / 2)
  ```
  to
  ```
  bid = option_data.get("bid", 0) or 0
  ask = option_data.get("ask", 0) or 0
  premium = bid   # CCs are SHORT — fill at bid
  if premium <= 0:
      continue
  ```
- Same fix pattern for the other short-leg strategies using mid (CSP line 329-331, bull-put short leg 565-570, bear-call short leg 690-695, Iron Condor short legs 1051-1054, Iron Butterfly short legs 1162-1165, Short Strangle 1375-1376). Keep LONG legs using ask (what you pay).
- Add liquidity filter **before scoring**: reject when
  ```
  bid <= 0 OR ask <= 0
  OR (ask - bid) / max(bid, 0.01) > 0.15   # >15% spread
  OR volume < 10 AND open_interest < 50     # illiquid
  ```

**File 2: [backend/services/position_opportunities_service.py](backend/services/position_opportunities_service.py)**

- Lines 409 and 554 already use `bid` — keep. Add the same liquidity filter there.

**File 3: [backend/services/options_hub/models.py](backend/services/options_hub/models.py)**

- Add `fetched_at: datetime` field to `StrategyOpportunity` and `OptionLeg`, populated when the chain snapshot is taken.
- Add `quote_source: Literal["bid", "ask"]` so the UI can label it ("Fill price: bid").

**File 4: [backend/routers/scanner.py](backend/routers/scanner.py) (lines ~3509, ~3530, ~3583)**

- Ensure the SELECT pulls `bid`, `ask`, `last_updated_at` from the premiums table.
- The emitted `DTEBucket` must return `premium = bid` (not premium_pct's source field if that's mid).
- Add `fetched_at` on each bucket so frontend can color-code age.

**File 5: [backend/services/tradier_options_service.py](backend/services/tradier_options_service.py)**

- Add a `force_refresh: bool = False` param to `get_options_chain_with_greeks()` that bypasses Redis and the in-memory cache and re-fetches from Tradier. This is the backend for the live-refresh button.
- Shorten chain TTL from 300s to **120s during market hours** (9:30–16:00 ET), keep 300s outside market hours.

**File 6 (new endpoint): [backend/routers/options_hub.py](backend/routers/options_hub.py)**

- Add `POST /api/options-hub/refresh-quote` that takes `{ symbol, strike, expiration, option_type }`, calls Tradier with `force_refresh=True` (and bypasses the premiums table), and returns the live `bid/ask/last/fetched_at`. Used by the per-row refresh button.

### Phase B — 3-Column Friday Layout

**File 7: [backend/routers/scanner.py](backend/routers/scanner.py) `get_consolidated_premiums`**

The existing CTE at lines 3496-3535 selects the `max_expirations=2` nearest Fridays ranked per-symbol. We extend it to also pick a "monthly-only" candidate:

1. Inside the `scored_expirations` CTE, classify each Friday expiration:
   - `is_weekly = EXISTS (another Friday for same symbol within ±7 days)` — detects whether the symbol has weekly options at all.
2. For each `symbol`, select three candidates:
   - `col_friday_1` = Friday with smallest DTE (any Friday)
   - `col_friday_2` = 2nd smallest Friday DTE (**only if the symbol has weeklies**, else NULL)
   - `col_monthly` = smallest-DTE 3rd-Friday-of-month expiration (**only if the symbol has NO weeklies**, else NULL)
3. Emit a stable 3-column descriptor in the response:
   ```json
   "expiration_dates": {
     "columns": [
       { "slot": "friday_1", "label": "Fri 4/18" },
       { "slot": "friday_2", "label": "Fri 4/25" },
       { "slot": "monthly",  "label": "Monthly" }
     ]
   }
   ```
4. Each row's `expiration_columns` dict must carry `slot` keys (`friday_1`, `friday_2`, `monthly`) in addition to date keys. For weekly-enabled symbols: `friday_1` and `friday_2` populated, `monthly` = `null`. For monthly-only symbols: `monthly` populated, `friday_1` and `friday_2` = `null`.

Note: "3rd Friday of month" is computed in SQL as `EXTRACT(DAY FROM expiration) BETWEEN 15 AND 21 AND EXTRACT(DOW FROM expiration) = 5`.

**File 8: [frontend/src/components/options/ConsolidatedPremiumsTable.tsx](frontend/src/components/options/ConsolidatedPremiumsTable.tsx)**

- Update the column-rendering loop at lines 378-390 to always render the 3 slots (`friday_1`, `friday_2`, `monthly`) in fixed order. Use the new `slot` key returned from backend instead of the free-form date key.
- For each cell: look up `row.expiration_columns?.[slot]`; render `—` when null.
- Header labels come from `expiration_dates.columns[i].label` so the actual Friday date is shown (e.g., "Fri 4/18", "Fri 4/25", "Monthly May 16").

**File 9: [frontend/src/components/scanner/CoveredCallsTab.tsx](frontend/src/components/scanner/CoveredCallsTab.tsx)**

- Replace the 13-col fixed grid (lines 314-346) with `<ConsolidatedPremiumsTable optionType="CALL" />`. Keep the existing filters UI (sector, min score, max price) but wire them through the consolidated endpoint's query params.
- The Margin CC-specific fields (margin_required, net_profit, margin_roi_annualized) move into the per-row expanded-detail modal — they're not removed, just not the default view.

**File 10: [frontend/src/pages/portfolio/PositionOpportunitiesTab.tsx](frontend/src/pages/portfolio/PositionOpportunitiesTab.tsx)**

- Already uses `ConsolidatedPremiumsTable`. No change needed — it automatically picks up the 3-column layout. Verify the PUT/CALL toggle still toggles `optionType` correctly.

### Phase C — Freshness UX (trust-building)

**File 11: [frontend/src/components/options/ConsolidatedPremiumsTable.tsx](frontend/src/components/options/ConsolidatedPremiumsTable.tsx)**

- In `DTECell` (where each premium cell renders), add a small age badge using `formatRelativeTime(bucket.fetched_at)`:
  - Green `<2 min`
  - Yellow `2–10 min`
  - Red `>10 min` + tooltip "Stale — click refresh"
- Add a tiny refresh icon button per row that POSTs to `/api/options-hub/refresh-quote` for each of the row's 3 slot cells in parallel, then mutates the React Query cache with the live quote so only that row re-renders.
- Add a `Fill@bid` tag next to each premium ("$0.42 @ bid") so the user understands what price we're quoting.

### Phase D — Wiring & verification

Backend changes require `docker compose up -d backend` (or `docker restart ada-backend` for pure Python edits). I will execute these directly after edits, not ask.

---

## Critical Files Summary

| File | Change |
|------|--------|
| [backend/services/options_hub/strategy_evaluator.py](backend/services/options_hub/strategy_evaluator.py) | Use `bid` for shorts, `ask` for longs; add liquidity filter |
| [backend/services/position_opportunities_service.py](backend/services/position_opportunities_service.py) | Add same liquidity filter |
| [backend/services/options_hub/models.py](backend/services/options_hub/models.py) | Add `fetched_at`, `quote_source` to `OptionLeg` / `StrategyOpportunity` |
| [backend/services/tradier_options_service.py](backend/services/tradier_options_service.py) | `force_refresh` param; dynamic TTL by market hours |
| [backend/routers/scanner.py](backend/routers/scanner.py) | 3-slot classifier (`friday_1`/`friday_2`/`monthly`); emit `fetched_at` per bucket |
| [backend/routers/options_hub.py](backend/routers/options_hub.py) | New `POST /refresh-quote` endpoint |
| [backend/routers/portfolio.py](backend/routers/portfolio.py) | Mirror scanner.py's 3-slot emission in `position-premiums-grid` |
| [frontend/src/components/options/ConsolidatedPremiumsTable.tsx](frontend/src/components/options/ConsolidatedPremiumsTable.tsx) | Fixed 3-slot column render; age badge; refresh button; `@bid` label |
| [frontend/src/components/scanner/CoveredCallsTab.tsx](frontend/src/components/scanner/CoveredCallsTab.tsx) | Replace 13-col grid with `ConsolidatedPremiumsTable optionType="CALL"` |

## Functions / Utilities to Reuse

- [ConsolidatedPremiumsTable.tsx](frontend/src/components/options/ConsolidatedPremiumsTable.tsx) `DTEBucket` / `DTECell` — render primitives, extend rather than reinvent
- [formatters.ts](frontend/src/utils/formatters.ts) `formatRelativeTime()` — for age badge (already imported line 11)
- [queryKeys.ts](frontend/src/hooks/queryKeys.ts) `QUERY_KEYS` — for refresh-button cache mutation
- [options_hub_scheduler.py](backend/services/options_hub_scheduler.py) existing scan cadence — no changes to scheduler, just cache TTL
- [tradier_options_service.py](backend/services/tradier_options_service.py) existing `get_options_chain_with_greeks` — add a param, don't duplicate

## Verification

1. **Premium accuracy** — pick 3 tickers (one liquid like SPY, one mid-cap, one low-liquidity) and compare scanner's quoted CC bid against Tradier's live bid within 30 seconds. Must match within rounding. Stale-cache cells must show the age badge.
2. **Liquidity filter** — assert no CC rows appear with `(ask - bid) / bid > 0.15` or `volume < 10 AND OI < 50`.
3. **3-column layout** — verify SPY (weekly) shows Fri 1 and Fri 2 populated, Monthly empty. Verify a monthly-only ticker (e.g. a small-cap) shows only the Monthly column populated.
4. **Owned-positions tab** — `/portfolio` › Opportunities › "Calls (CCs)" toggle renders the same 3-column layout, filtered to only held stock positions.
5. **Refresh button** — clicking it on a single row updates that row's premiums (verified by changing age badge from yellow → green) without a full refetch.
6. **Smoke tests** — `python .claude/skills/playwright-testing/runner.py smoke http://localhost:5420/scanner` and `http://localhost:5420/portfolio` must return `"status": "success"`.
7. **Backend endpoint checks** —
   ```
   curl 'http://localhost:8006/api/scanner/consolidated-premiums?option_type=CALL&page_size=5'
   curl -X POST 'http://localhost:8006/api/options-hub/refresh-quote' -d '{"symbol":"SPY","strike":525,"expiration":"2026-04-25","option_type":"CALL"}'
   ```
   Both must return 200 with expected schema.
