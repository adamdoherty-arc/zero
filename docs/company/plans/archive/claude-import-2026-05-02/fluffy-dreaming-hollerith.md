# Plan: Account Type Segmented Control on Positions Page

## Context

The user has both a **personal brokerage account** and a **Roth IRA** on Robinhood, but the Positions page currently mixes all positions together with no way to distinguish which account they belong to. Robinhood's API provides `account` URL and `account_number` fields on every position, plus a `type` field on account profiles — but the entire ADA pipeline currently discards this data. This plan adds account type tracking from Robinhood through to the frontend, with a segmented control to toggle between "All | Personal | Roth IRA".

## Changes

### 1. Backend: Extract account type from Robinhood

**File:** [portfolio_service.py](backend/services/portfolio_service.py)

- In `_fetch_positions_internal()` (~line 286): extract `type` and `account_number` from the existing `load_account_profile()` call (already fetched, just unused)
- Build an `account_number → account_type` mapping by fetching all linked account profiles. Strategy:
  - Extract unique `account_number` values from raw positions
  - For each unique account number, call `rh.profiles.load_account_profile(account_number=X)` to get its `type`
  - Cache this mapping for the duration of the sync (avoid redundant API calls)
- In `_get_stock_positions()` (~line 360): extract `account_number` from each raw position, look up `account_type` from the mapping, add both to the returned position dict
- In `_get_option_positions()` (~line 452): same — extract `account_number`, look up `account_type`, add to returned dict
- Map Robinhood's raw type values to display-friendly labels: `"individual"` → `"individual"`, `"roth_ira"` → `"roth_ira"`, etc.

### 2. Backend: Add DB columns for account type

**File:** [database_migrations.py](backend/infrastructure/database_migrations.py)

- Add `account_type VARCHAR(30)` and `account_id VARCHAR(30)` columns to:
  - `cached_stock_positions`
  - `cached_option_positions`
- Use `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` pattern (consistent with existing migrations)
- Add index on `account_type` for both tables (for potential future server-side filtering)

### 3. Backend: Store account type in sync

**File:** [positions_sync_service.py](backend/services/positions_sync_service.py)

- In `_sync_positions()`: pass `account_type` and `account_id` through to the UNNEST batch inserts
- Update the stock positions INSERT (~line 855) to include `account_type, account_id` columns
- Update the option positions INSERT (~line 960) to include `account_type, account_id` columns
- In `get_cached_positions()` (~line 1624): include `account_type` and `account_id` in SELECT queries for both stock and option positions

### 4. Frontend: Update TypeScript types

**File:** [types.ts](frontend/src/pages/portfolio/types.ts)

- Add to `StockPosition`: `account_type?: string; account_id?: string;`
- Add to `OptionPosition`: `account_type?: string; account_id?: string;`
- Add a type for account filter: `type AccountFilter = 'all' | 'individual' | 'roth_ira';`

### 5. Frontend: Add segmented control to PositionsTab

**File:** [PositionsTab.tsx](frontend/src/components/portfolio/PositionsTab.tsx)

- Add `accountFilter` state: `useState<AccountFilter>('all')`
- Derive available account types from positions data (so the toggle only shows accounts that actually have positions)
- Render a segmented control at the top of the positions area (above the stocks/options sections, below the equity cards):
  ```
  [ All (24) | Personal (18) | Roth IRA (6) ]
  ```
  - Each segment shows position count for that account
  - "All" selected by default (preserves current behavior)
  - Use existing shadcn/ui `Tabs` or button group pattern — check what's already used in the codebase
- Filter `stocks` and `options` arrays based on `accountFilter` before passing to `StocksWithCCTable` and `OptionsTableMini`
- Persist selected account filter to `localStorage` so it remembers across page refreshes

### 6. Frontend: Update summary metrics for filtered view

**File:** [PositionsTab.tsx](frontend/src/components/portfolio/PositionsTab.tsx)

- When `accountFilter !== 'all'`, recalculate summary metrics (total equity, total P&L, position count) from the filtered positions rather than using the server-provided summary
- Show a subtle indicator when viewing a filtered account (e.g., "Showing: Roth IRA" label) so the user knows the summary reflects a subset
- The `AllocationSidebar` should also receive filtered positions to show per-account allocation

## Files Modified (Summary)

| File | Change |
|------|--------|
| `backend/services/portfolio_service.py` | Extract account_type from Robinhood positions |
| `backend/infrastructure/database_migrations.py` | Add account_type/account_id columns |
| `backend/services/positions_sync_service.py` | Store and retrieve account_type |
| `frontend/src/pages/portfolio/types.ts` | Add account_type fields to position types |
| `frontend/src/components/portfolio/PositionsTab.tsx` | Add segmented control + client-side filtering |

## Verification

1. **Backend**: Restart backend container, trigger sync (`POST /api/portfolio/sync`), then check `GET /api/portfolio/positions/cached` — each stock and option position should include `account_type` and `account_id` fields
2. **Database**: Verify columns exist: `SELECT account_type, account_id FROM cached_stock_positions LIMIT 5`
3. **Frontend**: Navigate to `/portfolio`, verify segmented control appears with correct counts, toggle between accounts and confirm positions filter correctly, summary metrics update, and selection persists across page refresh
4. **Edge cases**: Verify "All" shows everything (matches current behavior), accounts with 0 positions are handled gracefully
