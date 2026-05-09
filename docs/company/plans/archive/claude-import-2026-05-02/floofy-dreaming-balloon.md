# Portfolio Opportunities → Scanner-Style Grid

## Context

**Problem:** The `Opportunities` sub-tab on the Portfolio page currently renders CSP/CC opportunities as collapsible per-symbol groups of `UnifiedAlertTile` cards (screenshot 1). This is verbose, limits visibility to one symbol at a time, and only surfaces one-strike-per-card. The user wants the same "CSP Scanner" multi-expiration grid layout used at [/scanner](frontend/src/components/scanner/) (screenshot 2) — one row per symbol, with strike + DTE + monthly% + premium + delta shown side-by-side across multiple expirations — but **scoped to every symbol the user holds in Robinhood** (stocks + CSP underlyings + CC underlyings), refreshed on every position sync.

**Intended outcome:**
- Replace the card-based Opportunities tab with a scanner-style grid table.
- Pull the symbol universe from all held positions (stocks + options, from the `cached_stock_positions` and `cached_option_positions` tables populated by the 30-minute Robinhood sync).
- Show both put (CSP) and call (CC) premiums via a Puts/Calls toggle on the table.
- Reuse the existing [`ConsolidatedPremiumsTable`](frontend/src/components/options/ConsolidatedPremiumsTable.tsx) component and the existing [`/api/scanner/consolidated-premiums`](backend/routers/scanner.py#L3214) endpoint to avoid rewriting scan/render/caching logic.

---

## Key Findings From Exploration

1. **`ConsolidatedPremiumsTable`** ([frontend/src/components/options/ConsolidatedPremiumsTable.tsx](frontend/src/components/options/ConsolidatedPremiumsTable.tsx)) already implements the exact layout in screenshot 2: one row per symbol, dynamic expiration columns, liquidity badges, CSP score column, Chain/TV action links, pagination, sort, stale-data warning, and a refresh button. It is already prop-driven and accepts filters.
2. **`/api/scanner/consolidated-premiums`** ([backend/routers/scanner.py:3214](backend/routers/scanner.py#L3214)) already accepts `symbols: str` (comma-separated) and filters the underlying `premium_opportunities` table to those symbols. It just needs an `option_type` param because it currently hardcodes `option_type = 'PUT'` at [scanner.py:3370](backend/routers/scanner.py#L3370).
3. **`premium_opportunities` table stores both puts and calls.** Per [backend/services/covered_call_scanner_service.py:17](backend/services/covered_call_scanner_service.py#L17): *"Storage: premium_opportunities table with option_type='CALL'"*. The CC scanner writes to the same table. No new table or new query is required to serve calls — only lift the hardcoded filter.
4. **Position source.** [`position_opportunities_service.py`](backend/services/position_opportunities_service.py) already queries positions from `cached_stock_positions` (quantity > 0) and `cached_option_positions` (quantity != 0), and the 30-minute Robinhood sync in [`positions_sync_service.py`](backend/services/positions_sync_service.py) keeps those tables fresh. I'll reuse the same read pattern.
5. **Current tab component to replace:** [frontend/src/pages/portfolio/PositionOpportunitiesTab.tsx](frontend/src/pages/portfolio/PositionOpportunitiesTab.tsx), mounted from [frontend/src/components/portfolio/PositionsTab.tsx:1086-1088](frontend/src/components/portfolio/PositionsTab.tsx#L1086).
6. **WebSocket sync hook** — `PositionsTab.tsx` lines 98-115 already listens for `sync_complete` and invalidates portfolio queries; the new grid will piggy-back on that pattern for auto-refresh after every Robinhood sync.

---

## Implementation Plan

### Backend (minimal, surgical)

**1. Add `option_type` query param to `/api/scanner/consolidated-premiums`** — [backend/routers/scanner.py:3214-3782](backend/routers/scanner.py#L3214)

- Add `option_type: str = Query("PUT", regex="^(PUT|CALL)$", description="PUT for CSPs, CALL for covered calls")` to the endpoint signature.
- Replace the hardcoded `option_type = 'PUT'` at [scanner.py:3370](backend/routers/scanner.py#L3370) with `option_type = '{option_type.upper()}'` (safe: regex-validated).
- No schema changes, no migration. The `premium_opportunities` table already stores both.
- Confirm the sort/pagination and detail-pass queries propagate the same filter (grep in that function for `'PUT'` and lift them all). The two-pass query at [scanner.py:3365-3605](backend/routers/scanner.py#L3365) uses `base_where` which already composes the new filter; just make sure the detail pass inherits it.

**2. Add `/api/portfolio/position-symbols` endpoint (tiny helper)** — new route in [backend/routers/portfolio.py](backend/routers/portfolio.py)

- Returns `{ "symbols": ["AAPL", "MSFT", ...] }` — the union of:
  - `SELECT DISTINCT symbol FROM cached_stock_positions WHERE quantity > 0`
  - `SELECT DISTINCT underlying FROM cached_option_positions WHERE quantity != 0`
- Cached 60s in Redis (`portfolio:position-symbols` key); invalidated on sync_complete broadcast.
- Single query via `UNION` — no N+1.
- Reuses existing `get_database()` pool and follows the batch-query pattern mandated by `magnus-database`.
- Why separate from the scanner call: keeps the scanner endpoint stateless, and the frontend needs the raw symbol list anyway for the auto-refresh trigger.

### Frontend

**3. New hook: [frontend/src/hooks/usePortfolioSymbols.ts](frontend/src/hooks/usePortfolioSymbols.ts)**

- React Query hook calling `GET /api/portfolio/position-symbols`.
- `staleTime: 5min`, `refetchInterval: 15min` (aligns with `usePositionOpportunities`).
- Invalidated by the existing `sync_complete` WebSocket handler in [PositionsTab.tsx:98-115](frontend/src/components/portfolio/PositionsTab.tsx#L98).

**4. Extend [`ConsolidatedPremiumsTable`](frontend/src/components/options/ConsolidatedPremiumsTable.tsx)**

- Add two new optional props (non-breaking for existing call sites in [ConsolidatedTab.tsx](frontend/src/components/scanner/ConsolidatedTab.tsx) and [UnifiedOptionsHub.tsx](frontend/src/pages/UnifiedOptionsHub.tsx)):
  - `symbolsOverride?: string[]` — when provided, sent as the `symbols` query param, overriding any `symbolSearch`.
  - `optionType?: 'PUT' | 'CALL'` — defaults to `'PUT'` to preserve current behaviour; passed through as `option_type`.
- Pass both into the `axiosInstance.get('/scanner/consolidated-premiums', { params })` call at [ConsolidatedPremiumsTable.tsx:201](frontend/src/components/options/ConsolidatedPremiumsTable.tsx#L201).
- Add them to `filtersKey` memoization at [line 175-178](frontend/src/components/options/ConsolidatedPremiumsTable.tsx#L175) so cache keys stay stable.
- Header label should reflect the mode: "CSP Scanner" when `optionType === 'PUT'`, "CC Scanner" when `'CALL'`. Small conditional at [line 238-247](frontend/src/components/options/ConsolidatedPremiumsTable.tsx#L238).

**5. Rewrite [frontend/src/pages/portfolio/PositionOpportunitiesTab.tsx](frontend/src/pages/portfolio/PositionOpportunitiesTab.tsx)** (replace, not augment)

Replace the entire card-based group implementation with:

```tsx
export function PositionOpportunitiesTab() {
  const [optionType, setOptionType] = useState<'PUT' | 'CALL'>('PUT');
  const { data: symbolsData, isPending } = usePortfolioSymbols();
  const symbols = symbolsData?.symbols ?? [];

  return (
    <div className="space-y-3">
      {/* Puts | Calls toggle */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1 bg-slate-800/50 rounded-lg p-1">
          <button onClick={() => setOptionType('PUT')} className={...}>
            Puts (CSPs)
          </button>
          <button onClick={() => setOptionType('CALL')} className={...}>
            Calls (CCs)
          </button>
        </div>
        <span className="text-xs text-slate-400">
          {symbols.length} held symbols
        </span>
      </div>

      {/* Empty state if no positions yet */}
      {!isPending && symbols.length === 0 && (
        <EmptyState message="No positions synced yet. Wait for the next Robinhood sync or trigger one manually." />
      )}

      {/* Scanner grid scoped to held symbols */}
      {symbols.length > 0 && (
        <ConsolidatedPremiumsTable
          limit={100}
          minPremium={0}
          symbolsOverride={symbols}
          optionType={optionType}
        />
      )}
    </div>
  );
}
```

- Delete all the obsolete card/grouping/filter/sort code (`FILTER_TABS`, `SORT_OPTIONS`, `grouped` useMemo, `expandedGroups` state, `UnifiedAlertTile` rendering, scan mutation UI — the table has its own Refresh button).
- The `usePositionOpportunities` / `usePositionOpportunitySummary` / `useScanPositionOpportunities` hooks and the `position_opportunities_service` scan pipeline remain untouched for now — other surfaces (alert mappers, stock detail) still reference `mapPositionOpportunityToUnifiedAlert`. Out of scope to remove them; they become silently unused by this tab.

**6. No changes** to [PositionsTab.tsx](frontend/src/components/portfolio/PositionsTab.tsx) — it already imports `PositionOpportunitiesTab` by name and mounts it at line 1086. Rewriting the file's content is enough.

---

## Critical Files

| File | Change |
|---|---|
| [backend/routers/scanner.py](backend/routers/scanner.py#L3214) | Add `option_type` query param, lift hardcoded `'PUT'` at L3370 |
| [backend/routers/portfolio.py](backend/routers/portfolio.py) | Add `GET /position-symbols` endpoint |
| [frontend/src/components/options/ConsolidatedPremiumsTable.tsx](frontend/src/components/options/ConsolidatedPremiumsTable.tsx) | Add `symbolsOverride` and `optionType` props |
| [frontend/src/hooks/usePortfolioSymbols.ts](frontend/src/hooks/usePortfolioSymbols.ts) | **New** — fetch held-symbols list |
| [frontend/src/pages/portfolio/PositionOpportunitiesTab.tsx](frontend/src/pages/portfolio/PositionOpportunitiesTab.tsx) | **Rewrite** — thin wrapper around the grid with puts/calls toggle |

## Reused (no changes)

- [backend/services/positions_sync_service.py](backend/services/positions_sync_service.py) — Robinhood sync already populates the position tables every 30 min.
- [backend/services/covered_call_scanner_service.py](backend/services/covered_call_scanner_service.py) — already writes CALL rows to `premium_opportunities`.
- [frontend/src/components/portfolio/PositionsTab.tsx](frontend/src/components/portfolio/PositionsTab.tsx) — `sync_complete` WebSocket handler already invalidates portfolio queries; just needs the new query key added to the invalidation list.

---

## Verification

### Backend
1. `docker restart ada-backend` after scanner.py and portfolio.py edits (per CLAUDE.md auto-restart rule). Check `docker logs ada-backend --tail 20` for clean startup.
2. `curl "http://localhost:8006/api/scanner/consolidated-premiums?option_type=PUT&symbols=AAPL,MSFT&page_size=10"` → expect 200 with `results` rows for AAPL and MSFT only, put premiums.
3. `curl "http://localhost:8006/api/scanner/consolidated-premiums?option_type=CALL&symbols=AAPL,MSFT&page_size=10"` → expect 200 with call premiums for same symbols. If empty, confirm CC scanner has run (check `premium_opportunities` row count via `SELECT COUNT(*) FROM premium_opportunities WHERE option_type='CALL'`).
4. `curl "http://localhost:8006/api/portfolio/position-symbols"` → expect `{ "symbols": [...] }` matching `SELECT DISTINCT symbol FROM cached_stock_positions UNION SELECT DISTINCT underlying FROM cached_option_positions`.

### Frontend
1. `python .claude/skills/playwright-testing/runner.py smoke http://localhost:5420/portfolio` → expect `"status": "success"`.
2. Navigate to `/portfolio` → click the **Opportunities** sub-tab → expect the scanner-style grid (rows per held symbol, multi-expiration columns with strike / DTE / monthly% / premium / delta) — NOT the card layout.
3. Click the **Calls (CCs)** toggle → expect the same rows with CALL premiums.
4. Confirm the symbol count chip matches the number of distinct symbols in the user's Robinhood portfolio.
5. Confirm empty state displays correctly when no positions are synced (can stub via temporarily disabling sync).

### Code graph impact check
- Run `detect_changes` on `scanner.py` to confirm no unexpected callers depend on `option_type = 'PUT'` being hardcoded.
- Run `trace_call_path` on `ConsolidatedPremiumsTable` to confirm no other call sites break from the two new optional props (both should remain defaulted).
