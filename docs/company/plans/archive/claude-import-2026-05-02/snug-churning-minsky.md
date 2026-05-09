# ADA Unified Intelligence Surface

## Context

**Problem**: You run scanners (Overkill Trading, Contrarian, CSP) and wonder if results are saved, where they go, and why you have to visit multiple tools to check on a stock. You want ADA to be ONE tool with ONE alerting mechanism that shows all data clearly per-symbol and per-position.

**What's actually happening today** (discovered in exploration):
- ✅ **Scanner results ARE saved.** Overkill writes to `overkill_scan_results` (every 30 min, 48hr TTL). Contrarian writes to `contrarian_scan_results` (every 60 min). CSP writes to `premium_opportunities`. Options Hub writes to `options_flow`. All persist to PostgreSQL.
- ✅ **Scanners DO generate alerts automatically.** Both Overkill (score≥70) and Contrarian (score≥65) call `_generate_hub_alerts()` → `real_time_alerts` table with 4-hour dedup.
- ✅ **Alert Hub IS the unified mechanism.** It already merges 12+ sources (OVERKILL, CONTRARIAN, CSP, EARNINGS, OPTIONS_HUB, PREDICTION, etc.) with scoring, dedup, and multi-channel routing (in-app, Discord, WebSocket, daily briefing).
- ❌ **The gap is surfacing.** Scanner results never reach the Stock Detail page, and positions have no per-row indicator of scanner/alert status. Users must visit `/alert-hub` separately.

**Intended outcome**: Surface the already-computed scanner/alert/opportunity data on the two pages where decisions are made — StockDetailPage (per-symbol) and PortfolioHub (per-position) — without duplicating scanner logic, building new alert generators, or adding new database tables.

**Key insight**: The backend already has `UnifiedSymbolDataService` at `backend/services/unified_symbol_data_service.py` with a "sections" pattern (parallel fetch, per-section TTL, graceful degradation). This is the natural extension point for symbol-level aggregation. For portfolio-level, a single new read-only router serves batch intelligence with an optional on-demand re-scan endpoint.

---

## User's Design Choices (confirmed)

1. **Stock Detail surface**: Enhance existing "Alerts" tab → rename to "Signals & Alerts" (don't add a 13th tab).
2. **Portfolio surface**: New compact "Signals" column on `StocksWithCCTable` with at-a-glance badges.
3. **Scope**: Surface existing persisted data **PLUS** add an on-demand "Scan my positions" button that triggers fresh Overkill + Contrarian scans scoped to held symbols.
4. **Real-time**: 60-second React Query polling. No new WebSocket work.

---

## Scope Summary

### IN SCOPE
1. Backend: extend `UnifiedSymbolDataService` with a new `SIGNALS` section.
2. Backend: NEW `portfolio_intelligence.py` router with:
   - `GET /api/portfolio/positions-intelligence` (batch read-only aggregator)
   - `POST /api/portfolio/scan-positions` (on-demand scan of held symbols)
3. Backend: register new router in `main.py`.
4. Frontend: extend `useUnifiedSymbolData` hook types to include `signals`.
5. Frontend: enhance `AlertsTab` with confluence banner, scanner score cards, and position opportunities row.
6. Frontend: rename StockDetailPage tab label "Alerts" → "Signals & Alerts" (id stays `alerts` for deep-link stability).
7. Frontend: NEW `usePositionsIntelligence` + `useScanPositions` hooks.
8. Frontend: NEW `PositionSignalsCell`, `ScannerScoreCard`, `SignalConfluenceBanner` components.
9. Frontend: add Signals column + "Scan Positions" button to `PositionsTab` / `StocksWithCCTable`.

### OUT OF SCOPE (guardrails)
- No new database tables or migrations (unless an index gap is discovered).
- No new scanner logic — `scan-positions` calls existing `overkill_bounce_scanner_service` + `contrarian_scanner_service` with a symbol filter.
- No changes to `alert_hub_service` or scanner routers.
- No new alert generators — scanners already write to `real_time_alerts` via `_generate_hub_alerts()`.
- No new WebSocket streams.
- No modifications to `backend/routers/portfolio.py` (new router keeps surface clean).
- No new smart-rule condition evaluators (`overkill_score_above` / `contrarian_score_above` already exist).

---

## Architecture

### Data Flow: Stock Detail (per-symbol)

```
User → /stocks/detail/AAPL?tab=alerts
  ↓
StockDetailPage → useUnifiedSymbolData({symbol:'AAPL', sections:['signals','alerts','technicals'], enabled: activeTab==='alerts'})
  ↓
GET /api/symbols/AAPL/unified?sections=signals,alerts,technicals
  ↓
UnifiedSymbolDataService._fetch_sections() runs asyncio.gather of:
  ├─ _fetch_technicals()  [existing]
  ├─ _fetch_alerts()      [existing → alert_hub_service.get_alerts_by_symbol]
  └─ _fetch_signals()     [NEW] internally parallel:
       ├─ latest overkill row (overkill_scan_results)
       ├─ latest contrarian row (contrarian_scan_results)
       ├─ top CSP opportunities (premium_opportunities)
       ├─ position opportunities (position_opportunities_service)
       └─ earnings proximity (earnings_calendar)
  ↓
AlertsTab renders: [Confluence Banner] [Overkill / Contrarian / Technical cards] [Active Alerts] [CSP Opps] [Position Opps]
```

### Data Flow: Portfolio (batch + on-demand scan)

```
User → /portfolio
  ↓
PositionsTab → usePositionsIntelligence() (60s stale)
  ↓
GET /api/portfolio/positions-intelligence
  ↓
portfolio_intelligence.get_positions_intelligence():
  1. SELECT symbols FROM cached_stock_positions WHERE quantity > 0
  2. asyncio.gather BATCH queries (ANY($1::text[])):
     ├─ overkill_scan_results DISTINCT ON (symbol)
     ├─ contrarian_scan_results DISTINCT ON (symbol)
     ├─ real_time_alerts GROUP BY symbol
     ├─ premium_opportunities GROUP BY symbol
     ├─ position_opportunities GROUP BY underlying
     └─ earnings_calendar WHERE symbol = ANY()
  3. Merge to {symbol → PositionIntelligenceSummary}
  ↓
StocksWithCCTable → PositionSignalsCell per row with compact badges
  ↓
Click badge → /stocks/detail/{symbol}?tab=alerts

User clicks "Scan My Positions" button:
  ↓
POST /api/portfolio/scan-positions  (body: optional {symbols?: string[]})
  ↓
portfolio_intelligence.scan_positions():
  1. Get held symbols (or accept override list)
  2. asyncio.gather:
     ├─ overkill_scanner_service.run_scan(symbols=held)
     └─ contrarian_scanner_service.run_scan(symbols=held)
  3. Return summary {overkill:{scanned,alerts}, contrarian:{scanned,alerts}}
  ↓
Frontend invalidates ['portfolio','positions-intelligence'] → refetch
```

---

## Backend Implementation

### 1. Extend `UnifiedSymbolDataService`

**File**: `c:\code\ADA\backend\services\unified_symbol_data_service.py`

Changes:
- Add `SIGNALS = "signals"` to `DataSection` enum.
- Add `SECTION_TTL[DataSection.SIGNALS] = 120` (2 min).
- Add dataclass:

```python
@dataclass
class SignalsData:
    overkill: dict[str, Any] | None = None
    contrarian: dict[str, Any] | None = None
    csp_opportunities: list[dict[str, Any]] = field(default_factory=list)
    position_opportunities: list[dict[str, Any]] = field(default_factory=list)
    earnings_proximity_days: int | None = None
    signal_strength: str = "neutral"  # strong_bullish|bullish|neutral|bearish|strong_bearish
    confluence_count: int = 0
    staleness_warning: str | None = None  # set if data >4hr old
    source: str = "aggregator"
```

- Add `signals: SignalsData = field(default_factory=SignalsData)` to `UnifiedSymbolData` + update `to_dict()`.
- Implement `_fetch_signals(symbol, data)` with parallel `asyncio.gather(..., return_exceptions=True)` calling:
  - `_fetch_latest_overkill_score(db, symbol)` — single row SELECT from `overkill_scan_results WHERE symbol=$1 AND is_active=TRUE ORDER BY scanned_at DESC LIMIT 1`
  - `_fetch_latest_contrarian_score(db, symbol)` — same pattern from `contrarian_scan_results`
  - `_fetch_csp_opportunities_for_symbol(db, symbol, limit=5)` — from `premium_opportunities` ORDER BY score DESC NULLS LAST
  - `_fetch_position_opportunities_for_symbol(symbol, limit=5)` — via `get_position_opportunities_service().get_cached_opportunities(symbol=symbol)`
  - `_fetch_earnings_proximity(db, symbol)` — `earnings_calendar` next date
- Add `_compute_confluence(overkill, contrarian, technicals, options_flow)` → returns `(signal_strength, confluence_count)` by tallying bullish/bearish votes.
- Register dispatch in `_fetch_sections` (add `DataSection.SIGNALS` branch).
- Mirror existing error handling: wrap in `try/except`, log warning on failure, store `None` sections rather than raising.

**No router changes needed**: `/api/symbols/{symbol}/unified?sections=signals` will work automatically because the router already parses comma-separated sections from the enum.

### 2. NEW `portfolio_intelligence.py` router

**File**: `c:\code\ADA\backend\routers\portfolio_intelligence.py` (CREATE)

Endpoints:

#### `GET /api/portfolio/positions-intelligence`

Read-only batch aggregator. Returns:

```python
class PositionIntelligenceSummary(BaseModel):
    symbol: str
    overkill_score: float | None = None
    overkill_grade: str | None = None
    overkill_signal: str | None = None  # BUY | REVERSAL_SETUP | CORRECTION_WATCH
    overkill_scanned_at: datetime | None = None
    contrarian_score: float | None = None
    contrarian_grade: str | None = None
    active_alerts_count: int = 0
    highest_alert_priority: str = "none"  # HIGH|MEDIUM|LOW|none
    csp_opportunity_count: int = 0
    position_opportunity_count: int = 0
    latest_signal_strength: str = "neutral"
    risk_flags: list[str] = []  # ["earnings_7d", "contrarian_avoid", "data_stale"]
    earnings_days: int | None = None
    last_updated: datetime

class PositionsIntelligenceResponse(BaseModel):
    positions: dict[str, PositionIntelligenceSummary]
    total: int
    generated_at: datetime
```

Implementation steps (all use `ANY($1::text[])` batch pattern — no N+1):
1. `SELECT DISTINCT symbol FROM cached_stock_positions WHERE quantity > 0`
2. `asyncio.gather` of 6 batch queries (overkill, contrarian, alert counts, CSP counts, position_opp counts, earnings proximity)
3. Merge in Python → `{symbol: PositionIntelligenceSummary}`
4. Wrap in `try/except` per query — partial failures return `data_unavailable` flag, not a 500

#### `POST /api/portfolio/scan-positions`

On-demand fresh scan of held symbols. Request body (optional): `{symbols?: string[], scanners?: ["overkill","contrarian"]}`.

Implementation:
1. Resolve symbols: use request body if provided, otherwise query held positions.
2. `asyncio.gather`:
   - `overkill_bounce_scanner_service.run_scan(symbols=held_symbols)` — the existing service supports symbol scoping; if not, pass via its filter parameter or call in a loop with a semaphore (`asyncio.Semaphore(3)` — matches Ollama concurrency convention).
   - `contrarian_scanner_service.run_scan(symbols=held_symbols)`
3. Both scanners already persist results AND call `_generate_hub_alerts()` internally — no extra alert wiring needed.
4. Return:
   ```python
   {
     "status": "complete",
     "scanned_symbols": [...],
     "overkill": {"scanned": 12, "alerts_created": 3, "top_score": 82},
     "contrarian": {"scanned": 12, "alerts_created": 1, "top_score": 71},
     "duration_ms": 8432,
   }
   ```
5. Long-running guard: if scan takes > 30s, return 202 with a job id and let the frontend poll. For MVP, accept synchronous completion since the universe is small (held positions only, usually < 30).

**Pre-flight check**: Before writing the scan endpoint, verify `overkill_bounce_scanner_service` and `contrarian_scanner_service` accept a `symbols` argument to `run_scan()`. If not, add an optional `symbols: list[str] | None = None` parameter that short-circuits the default universe. This is the only modification to existing scanner services allowed by scope.

### 3. Register router in `main.py`

**File**: `c:\code\ADA\backend\main.py`

Add next to existing `position_opportunities` registration:
```python
from backend.routers import portfolio_intelligence
app.include_router(portfolio_intelligence.router)
```

### 4. Index verification (magnus-database skill)

Before Phase 3 ships, invoke the `magnus-database` skill to verify indexes exist on:
- `overkill_scan_results(symbol, scanned_at DESC)` + `(is_active)`
- `contrarian_scan_results(symbol, scanned_at DESC)` + `(is_active)`
- `real_time_alerts(symbol, is_active)`
- `premium_opportunities(symbol, is_active)`
- `position_opportunities(underlying)`
- `earnings_calendar(symbol, next_earnings_date)`

If any index is missing, create a migration. EXPLAIN ANALYZE must show `Index Scan` on all batch queries.

---

## Frontend Implementation

### 5. Extend `useUnifiedSymbolData` types

**File**: `c:\code\ADA\frontend\src\hooks\useUnifiedSymbolData.ts`

- Add `'signals'` to the `DataSection` TS union type.
- Add `SignalsData` interface mirroring backend dataclass.
- Add `signals: SignalsData` to `UnifiedSymbolData`.
- Add `SECTION_STALE_TIMES.signals = 2 * 60 * 1000` (2 min).

### 6. NEW Stock Detail subcomponents

**CREATE** `c:\code\ADA\frontend\src\components\stock-detail\SignalConfluenceBanner.tsx`
- Props: `{ signalStrength, confluenceCount, sources: string[] }`
- Color-coded bar (green=strong_bullish, emerald=bullish, slate=neutral, amber=bearish, red=strong_bearish)
- Lists contributing sources as chips: "Overkill 82", "RSI oversold", "Contrarian 68"

**CREATE** `c:\code\ADA\frontend\src\components\stock-detail\ScannerScoreCard.tsx`
- Props: `{ label, score, grade, badge, scannedAt, onViewDetail }`
- Compact gauge-style score display (0-100)
- Grade badge (A/B/C/D/F)
- Signal type badge if present
- "View detail →" link navigates to the scanner hub for that symbol
- Defensive math: `Number(score ?? 0).toFixed(0)`

### 7. Enhance `AlertsTab.tsx`

**File**: `c:\code\ADA\frontend\src\pages\stock-detail\tabs\AlertsTab.tsx`

New layout (top → bottom):
1. `<SignalConfluenceBanner>` — if `signals.signal_strength !== 'neutral'` or `confluence_count > 0`
2. Row of 3 `<ScannerScoreCard>` components — Overkill, Contrarian, Technical
3. **EXISTING** Active Alerts section (untouched)
4. **EXISTING** CSP Opportunities section (untouched)
5. NEW Position Opportunities row — CSP alternatives / CC rolls if `signals.position_opportunities.length > 0`

Props: accept `signalsData?: SignalsData` in addition to existing alerts data.

### 8. Modify `StockDetailPage.tsx`

**File**: `c:\code\ADA\frontend\src\pages\StockDetailPage.tsx`

- Rename tab label: `{ id: 'alerts', label: 'Signals & Alerts', icon: <AlertCircle /> }` (id stays `alerts`).
- Replace any existing `useAlertsBySymbol` call (or augment) with:
  ```tsx
  const { data: unified, isPending } = useUnifiedSymbolData({
    symbol: symbol || '',
    sections: ['signals', 'alerts', 'technicals'],
    enabled: activeTab === 'alerts',
  });
  ```
- Pass `signalsData={unified?.signals}` to `<AlertsTab>`.

### 9. NEW Portfolio hooks

**CREATE** `c:\code\ADA\frontend\src\hooks\usePositionsIntelligence.ts`
- React Query v5 `useQuery` (use `isPending` not `isLoading`)
- Query key: `['portfolio', 'positions-intelligence']`
- `staleTime: 60_000`, `refetchOnWindowFocus: false`, `retry: 2`
- Returns typed `PositionsIntelligenceResponse`

**CREATE** `c:\code\ADA\frontend\src\hooks\useScanPositions.ts`
- React Query `useMutation`
- `mutationFn` → `axiosInstance.post('/portfolio/scan-positions', body)`
- `onSuccess` → `queryClient.invalidateQueries(['portfolio', 'positions-intelligence'])` AND `(['alert-hub'])`
- Returns mutation with `isPending` for button loading state

### 10. NEW `PositionSignalsCell.tsx`

**CREATE** `c:\code\ADA\frontend\src\components\portfolio\PositionSignalsCell.tsx`
- Props: `{ intel?: PositionIntelligenceSummary, symbol: string }`
- Renders up to 4 compact badges (hide if null/zero):
  - Overkill: score chip (green ≥70, amber 50-69, slate < 50)
  - Contrarian: similar
  - Alert count: red dot with number if `active_alerts_count ≥ 1`
  - CSP opp: emerald dot if `csp_opportunity_count ≥ 1`
- Tooltip on hover with full detail text
- Click on cell → navigate to `/stocks/detail/{symbol}?tab=alerts`
- Use `Number(intel?.overkill_score ?? 0).toFixed(0)` for defensive math

### 11. Add Signals column + Scan button to `StocksWithCCTable.tsx`

**File**: `c:\code\ADA\frontend\src\components\portfolio\StocksWithCCTable.tsx`

- Import `usePositionsIntelligence` + `useScanPositions`.
- Call `const { data: intel } = usePositionsIntelligence();` at top of component.
- Call `const scanMutation = useScanPositions();` for the scan button.
- Add new column header: `<th className="pb-2 px-2 text-center whitespace-nowrap">Signals</th>` positioned between "Stock P&L" and "CC Status".
- Render `<PositionSignalsCell intel={intel?.positions[stock.symbol]} symbol={stock.symbol} />` in each row.
- Add a "Scan Positions" button (top-right of table header area) wired to `scanMutation.mutate()`:
  - Disabled while `scanMutation.isPending`
  - Shows loading spinner + "Scanning..." text during scan
  - Toast on success with counts: "Scanned 12 positions — 3 Overkill + 1 Contrarian alerts"

---

## Critical Files

### CREATE (7 files)

| File | Purpose |
|---|---|
| `c:\code\ADA\backend\routers\portfolio_intelligence.py` | Batch intelligence + on-demand scan endpoints |
| `c:\code\ADA\frontend\src\components\stock-detail\SignalConfluenceBanner.tsx` | Confluence strength banner for AlertsTab |
| `c:\code\ADA\frontend\src\components\stock-detail\ScannerScoreCard.tsx` | Reusable Overkill/Contrarian/Technical scorecard |
| `c:\code\ADA\frontend\src\hooks\usePositionsIntelligence.ts` | React Query hook for batch endpoint |
| `c:\code\ADA\frontend\src\hooks\useScanPositions.ts` | React Query mutation hook for on-demand scan |
| `c:\code\ADA\frontend\src\components\portfolio\PositionSignalsCell.tsx` | Compact badge cell for portfolio table |

### MODIFY (6 files)

| File | Changes |
|---|---|
| `c:\code\ADA\backend\services\unified_symbol_data_service.py` | Add `SIGNALS` section, `SignalsData` dataclass, `_fetch_signals` + helpers, dispatch in `_fetch_sections`, extend `to_dict()` |
| `c:\code\ADA\backend\services\overkill_bounce_scanner_service.py` | Add optional `symbols: list[str] \| None` parameter to `run_scan()` if not already present |
| `c:\code\ADA\backend\services\contrarian_scanner_service.py` | Same `symbols` parameter addition if not present |
| `c:\code\ADA\backend\main.py` | Register `portfolio_intelligence` router (2 lines) |
| `c:\code\ADA\frontend\src\hooks\useUnifiedSymbolData.ts` | Add `'signals'` to section union, add `SignalsData` interface, add `signals` field, add stale time entry |
| `c:\code\ADA\frontend\src\pages\stock-detail\tabs\AlertsTab.tsx` | Accept `signalsData` prop, render banner + 3 score cards + position opportunities row above existing alerts list |
| `c:\code\ADA\frontend\src\pages\StockDetailPage.tsx` | Rename tab label to "Signals & Alerts", wire `useUnifiedSymbolData` for signals+alerts+technicals, pass `signalsData` to `<AlertsTab>` |
| `c:\code\ADA\frontend\src\components\portfolio\StocksWithCCTable.tsx` | Import intelligence hooks, add Signals column + PositionSignalsCell, add "Scan Positions" button |

### READ for context (no modification)

- `c:\code\ADA\backend\services\alert_hub_service.py` — existing `get_alerts_by_symbol` behavior
- `c:\code\ADA\backend\services\position_opportunities_service.py` — `get_cached_opportunities(symbol=...)` signature
- `c:\code\ADA\.claude\memory\topics\alert-hub.md` — alert source map
- `c:\code\ADA\.claude\memory\topics\scanner.md` — Overkill/Contrarian scoring and table schema

---

## Reused Existing Infrastructure

| Need | Reuse (not rebuild) |
|---|---|
| Symbol-level aggregation | `UnifiedSymbolDataService` (parallel fetch + per-section TTL) |
| Alert lookup by symbol | `alert_hub_service.get_alerts_by_symbol` |
| Scanner persistence | `overkill_scan_results` / `contrarian_scan_results` / `premium_opportunities` tables |
| Scanner alert generation | Existing `_generate_hub_alerts()` in each scanner service (unchanged) |
| Position opportunities | `position_opportunities_service.get_cached_opportunities` |
| Smart rules on scanner scores | Existing `overkill_score_above` / `contrarian_score_above` evaluators |
| Alert delivery channels | Existing Discord/in-app/WebSocket/daily briefing routing |
| React Query patterns | `useUnifiedSymbolData` pattern + v5 `isPending` |

---

## Implementation Phases

### Phase 1: Backend Signals Aggregator (symbol surface)
- Extend `UnifiedSymbolDataService` with SIGNALS section
- Verify indexes via `magnus-database` skill
- `docker compose up -d backend`
- Curl test: `curl 'http://localhost:8006/api/symbols/AAPL/unified?sections=signals'` → 200 with populated signals
- `docker logs ada-backend --tail 30` → no errors
- **Acceptance**: endpoint returns `signals` object, partial failures return null fields not 500, p95 latency < 400ms warm / < 1200ms cold

### Phase 2: Frontend Stock Detail surface
- Extend `useUnifiedSymbolData.ts` types
- Create `SignalConfluenceBanner` + `ScannerScoreCard`
- Modify `AlertsTab.tsx` to render new sections
- Modify `StockDetailPage.tsx` (tab rename + hook wiring)
- Run smoke test: `python .claude/skills/playwright-testing/runner.py smoke http://localhost:5420/stocks/detail/AAPL?tab=alerts`
- **Acceptance**: smoke test returns `"status": "success"`, banner + 3 score cards render, no `isLoading` (must use `isPending`), no bare `.toFixed()` without `Number()`

### Phase 3: Backend Portfolio Intelligence router
- Add optional `symbols` parameter to scanner services if missing
- Create `portfolio_intelligence.py` router with both endpoints
- Register in `main.py`
- `docker compose up -d backend`
- Curl test `GET /portfolio/positions-intelligence` → 200 with populated map
- Curl test `POST /portfolio/scan-positions` with `{"symbols":["AAPL","MSFT"]}` → 200 with scan summary
- EXPLAIN ANALYZE each batch query → confirm `Index Scan` on all
- **Acceptance**: batch endpoint query count ≤ 8 total regardless of position count, no N+1, scan endpoint completes in < 30s for typical portfolios

### Phase 4: Frontend Portfolio surface
- Create `usePositionsIntelligence` + `useScanPositions` hooks
- Create `PositionSignalsCell` component
- Modify `StocksWithCCTable.tsx` — add column + "Scan Positions" button
- Run smoke test on `/portfolio`
- Manual: click "Scan Positions", verify toast + badge refresh
- **Acceptance**: smoke test passes, column renders without layout shift, scan button disables during mutation, badges update within 2s of scan completion (via invalidation)

---

## Verification (End-to-End)

After all phases land:

### Backend verification
```bash
# 1. Symbol-level signals
curl -s 'http://localhost:8006/api/symbols/AAPL/unified?sections=signals' | jq '.signals'

# 2. Portfolio batch intelligence
curl -s 'http://localhost:8006/api/portfolio/positions-intelligence' | jq '.positions | length'

# 3. On-demand scan
curl -s -X POST 'http://localhost:8006/api/portfolio/scan-positions' \
  -H 'Content-Type: application/json' -d '{}' | jq

# 4. Container health
docker logs ada-backend --tail 50 | grep -iE 'error|exception'
```

### Frontend verification
```bash
# Smoke tests
python .claude/skills/playwright-testing/runner.py smoke http://localhost:5420/stocks/detail/AAPL?tab=alerts
python .claude/skills/playwright-testing/runner.py smoke http://localhost:5420/portfolio
```

### Code graph / impact verification
Run `detect_changes` (codebase-memory MCP) on the diff to confirm blast radius is limited to the 13 files listed.

### Manual UAT
1. Open `/stocks/detail/AAPL?tab=alerts` — see confluence banner + Overkill + Contrarian + Technical cards + existing alerts + CSP opps + position opps
2. Open `/portfolio` — see Signals column on positions table with compact badges
3. Click "Scan Positions" — button shows loading, toast confirms scan with counts, badges refresh
4. Click a badge — navigates to `/stocks/detail/{symbol}?tab=alerts`
5. Compare with `/alert-hub` — scanner-generated alerts for your held symbols should appear there as well (confirms ONE alerting mechanism)

### Code quality gates (enforced by orchestrator)
- No `.toFixed()` without `Number()` wrapper
- No `isLoading` (v5 uses `isPending`)
- No hardcoded ports (axiosInstance has `/api` baseURL)
- No N+1 queries — all batch queries use `ANY($1::text[])`
- All new SQL queries use indexed columns (EXPLAIN ANALYZE confirms)
- `magnus-database` skill invoked for index verification
- `magnus-api` skill invoked for new FastAPI endpoints
- `magnus-hooks` skill invoked for new React Query hooks

---

## Minimum Disruption Summary

| Metric | Count |
|---|---|
| New database tables | 0 |
| New migrations | 0 (unless index gap found) |
| New scanner logic | 0 (on-demand scan reuses existing services) |
| New alert generators | 0 |
| New backend routers | 1 (`portfolio_intelligence.py`) |
| Modified backend files | 4 (`unified_symbol_data_service.py`, `main.py`, 2 scanner services for `symbols` param) |
| New backend endpoints | 2 (`GET positions-intelligence`, `POST scan-positions`) |
| Extended backend endpoints | 1 (`/api/symbols/{symbol}/unified` — new `signals` section) |
| New frontend components | 3 |
| New frontend hooks | 2 |
| Modified frontend files | 3 |
| New WebSocket streams | 0 |

**Result**: ONE tool, ONE alerting mechanism. All scanner data surfaces contextually on StockDetail (per-symbol) and PortfolioHub (per-position). On-demand scanning of held positions included. No scope creep — pure integration work on top of infrastructure that's already running.
