# Plan: Surface CC Coverage View + Per-Position Scanner Signals + Auto-Alerts

## Context

The user reports that a feature on the Positions page "looks to have disappeared": a section showing every held stock with its covered-call coverage status, plus scanner signals (Overkill, Contrarian, etc.) applied to held positions. They want all of those indicators visible **on the positions page** for each stock and each covered call, in one place, with alerts automatically created for any flagged stock.

**What's actually true**:
- The feature is **not deleted** — it's hidden. [StocksWithCCTable.tsx](frontend/src/components/portfolio/StocksWithCCTable.tsx) is fully built (596 LOC), shows coverage status (COVERED/CC READY/UNCOVERED/INELIGIBLE), missed CC income, and now includes a brand-new `Signals` column powered by [PositionSignalsCell.tsx](frontend/src/components/portfolio/PositionSignalsCell.tsx) (overkill/contrarian/alerts/CSP/opportunities/earnings badges).
- However, in [PositionsTab.tsx:902-913](frontend/src/components/portfolio/PositionsTab.tsx#L902-L913) it is wrapped in a `<details>` element **collapsed by default** — appearing "disappeared".
- The new backend [portfolio_intelligence.py](backend/routers/portfolio_intelligence.py) router (mounted at [main.py:2530](backend/main.py#L2530)) provides `GET /api/portfolio/positions-intelligence` and `POST /api/portfolio/scan-positions`. The hook [usePositionsIntelligence.ts](frontend/src/hooks/usePositionsIntelligence.ts) polls every 60s.
- The **CC group headers** in the Options sub-tab ([PositionsTab.tsx:1019-1049](frontend/src/components/portfolio/PositionsTab.tsx#L1019-L1049)) currently show only `PositionIntelligenceBadge` — they do NOT show the rich scanner badges, so the user can't see Overkill/Contrarian status next to a covered call.
- **No scheduled job** runs the position scan — it's only triggered when the user manually clicks "Scan Positions". So Alert Hub does not auto-fire when scanners flag a held stock.

**Goal**: Make the existing feature discoverable as a first-class Portfolio sub-tab, mirror the same scanner badges on covered-call rows in the Options sub-tab, and run the position scanner on a recurring schedule so high-score signals automatically create alerts.

---

## Approach

Three small, surgical changes — no new components, no new endpoints, no DB migrations. Everything reuses existing infrastructure.

### 1. Promote `StocksWithCCTable` to a first-class Portfolio sub-tab

File: [frontend/src/components/portfolio/PositionsTab.tsx](frontend/src/components/portfolio/PositionsTab.tsx)

- Extend the `activeSubTab` state union from `'options' | 'opportunities' | 'simulator'` to add `'coverage'` ([line 144](frontend/src/components/portfolio/PositionsTab.tsx#L144)).
- Add a new tab button alongside Options/Opportunities/Simulator at [lines 921-940](frontend/src/components/portfolio/PositionsTab.tsx#L921-L940). Label: **"Stocks & CCs"**, icon `ShieldCheck` (lucide-react). Show a small red dot badge on the tab when `ccData?.summary.positions_without_cc > 0` (sourced from the existing `useCCProfitAnalysis()` hook already called at [line 198](frontend/src/components/portfolio/PositionsTab.tsx#L198)).
- Add the matching tab panel inside the conditional render block (after the simulator panel, around [line 1144](frontend/src/components/portfolio/PositionsTab.tsx#L1144)):
  ```tsx
  {activeSubTab === 'coverage' && (
    <div className="p-4">
      <StocksWithCCTable
        stocks={sortedStocks}
        onSelect={setSelectedSymbol}
        onSimulate={handleOpenSimulator}
        selectedSymbol={selectedSymbol}
        hideAmounts={hideAmounts}
        totalEquity={liveTotalEquity}
      />
    </div>
  )}
  ```
- **Delete** the redundant collapsed `<details>` wrapper at [lines 902-913](frontend/src/components/portfolio/PositionsTab.tsx#L902-L913). The table now lives in the new tab as its primary home.
- Keep the default sub-tab as `'options'` to avoid disrupting muscle memory — the badge dot draws attention to the new tab when there's uncovered exposure.

### 2. Add scanner signal badges to covered-call group headers

Same file: [frontend/src/components/portfolio/PositionsTab.tsx](frontend/src/components/portfolio/PositionsTab.tsx)

- Import the existing hook and component at the top:
  ```tsx
  import { usePositionsIntelligence } from '@/hooks/usePositionsIntelligence';
  import { PositionSignalsCell } from '@/components/portfolio/PositionSignalsCell';
  ```
- Call the hook once near the top of the component (next to the other hook calls around [line 198](frontend/src/components/portfolio/PositionsTab.tsx#L198)):
  ```tsx
  const { data: intelData } = usePositionsIntelligence();
  ```
- In the option group header at [line 1021-1023](frontend/src/components/portfolio/PositionsTab.tsx#L1021-L1023), add the signals cell next to the existing `PositionIntelligenceBadge`:
  ```tsx
  <span className="font-medium text-white">{underlying}</span>
  <PositionIntelligenceBadge symbol={underlying} />
  <PositionSignalsCell intel={intelData?.positions[underlying]} symbol={underlying} />
  ```
- React Query deduplicates the request — the hook is already called inside `StocksWithCCTable`, so this second call shares the same cache key (`['portfolio', 'positions-intelligence']`) and incurs zero extra network cost.

This means **every CC and CSP group on the Options tab** now shows the same Overkill/Contrarian/Alerts/CSP/OPP/ER chips as the stocks table — exactly what the user asked for.

### 3. Schedule automatic position scans (and therefore automatic alerts)

File: [backend/services/scheduled_tasks.py](backend/services/scheduled_tasks.py)

- Add a new async task `scheduled_position_scan()` near the other scanner-related tasks. It mirrors the logic of the existing `POST /api/portfolio/scan-positions` endpoint at [portfolio_intelligence.py:373-465](backend/routers/portfolio_intelligence.py#L373-L465):
  ```python
  async def scheduled_position_scan():
      """Run Overkill + Contrarian scanners on all currently-held stock positions.
      Both scanner services internally call _generate_hub_alerts(), so any
      score >= threshold (Overkill: 70, Contrarian: 65) automatically creates
      a real_time_alerts row that surfaces in the Alert Hub."""
      from backend.infrastructure.database import get_database
      from backend.services.overkill_bounce_scanner_service import get_overkill_scanner_service
      from backend.services.contrarian_scanner_service import get_contrarian_scanner_service

      db = await get_database()
      rows = await db.fetch(
          "SELECT DISTINCT symbol FROM cached_stock_positions "
          "WHERE quantity > 0 AND symbol IS NOT NULL ORDER BY symbol"
      )
      symbols = [r["symbol"] for r in rows]
      if not symbols:
          return {"status": "skipped", "reason": "no_held_positions"}

      overkill = get_overkill_scanner_service()
      contrarian = get_contrarian_scanner_service()
      results = await asyncio.gather(
          overkill.scan_symbols(symbols=symbols, min_score=0.0),
          contrarian.scan_symbols(symbols=symbols, min_score=0.0),
          return_exceptions=True,
      )
      # Log structured summary; alerts are created inside the scanner services.
      logger.info("scheduled_position_scan_complete",
                  symbols=len(symbols),
                  overkill_ok=not isinstance(results[0], Exception),
                  contrarian_ok=not isinstance(results[1], Exception))
      return {"status": "complete", "symbol_count": len(symbols)}
  ```
- Register the cron job in the scheduler init block (where the other `_scheduler.add_job(...)` calls live around [line 1750+](backend/services/scheduled_tasks.py#L1750)). Run **4× during market hours, Mon-Fri**, staggered to avoid overlap with `intraday_alert_refresh` ([line 1862](backend/services/scheduled_tasks.py#L1862)):
  ```python
  for hour, minute, suffix in [(9, 45, 'open'), (11, 30, 'midmorning'),
                                 (13, 30, 'afternoon'), (15, 15, 'preclose')]:
      _scheduler.add_job(
          _guarded(scheduled_position_scan),
          'cron',
          hour=hour, minute=minute,
          day_of_week='mon-fri',
          timezone=ZoneInfo('America/New_York'),
          id=f'scheduled_position_scan_{suffix}',
          name='Scan held positions with Overkill+Contrarian scanners',
          replace_existing=True,
          max_instances=1,
      )
  ```
- Use the existing `_guarded()` wrapper used by every other scheduled job in the file.

---

## Files Modified

| File | Change |
|------|--------|
| [frontend/src/components/portfolio/PositionsTab.tsx](frontend/src/components/portfolio/PositionsTab.tsx) | Add `'coverage'` sub-tab hosting `StocksWithCCTable`; add `PositionSignalsCell` to option group headers; delete the collapsed `<details>` wrapper at lines 902-913 |
| [backend/services/scheduled_tasks.py](backend/services/scheduled_tasks.py) | Add `scheduled_position_scan()` task and 4× daily cron registration |

## Existing Code Reused (Zero New Components)

- [usePositionsIntelligence.ts](frontend/src/hooks/usePositionsIntelligence.ts) — React Query hook polling every 60s
- [useCCProfitAnalysis.ts](frontend/src/hooks/useCCProfitAnalysis.ts) — already wired in PositionsTab.tsx:198, deduplicated via React Query
- [PositionSignalsCell.tsx](frontend/src/components/portfolio/PositionSignalsCell.tsx) — multi-badge cell already complete
- [StocksWithCCTable.tsx](frontend/src/components/portfolio/StocksWithCCTable.tsx) — full coverage table already complete
- [portfolio_intelligence.py](backend/routers/portfolio_intelligence.py) — both endpoints already mounted
- `get_overkill_scanner_service().scan_symbols()` ([overkill_bounce_scanner_service.py:459](backend/services/overkill_bounce_scanner_service.py#L459)) — internally writes high-score matches to `real_time_alerts` via `_generate_hub_alerts()`
- `get_contrarian_scanner_service().scan_symbols()` ([contrarian_scanner_service.py:388](backend/services/contrarian_scanner_service.py#L388)) — same pattern
- `_guarded()` wrapper in scheduled_tasks.py — used by all 30+ existing cron jobs

## Verification

### Backend (after `docker restart ada-backend`)
1. Confirm scheduler picked up the new jobs:
   ```bash
   docker logs ada-backend --tail 200 | grep -i scheduled_position_scan
   ```
   Expect 4 lines mentioning `scheduled_position_scan_open`, `_midmorning`, `_afternoon`, `_preclose`.
2. Manually trigger the underlying scan to confirm wiring (idempotent — also runs on schedule):
   ```bash
   curl -X POST http://localhost:8006/api/portfolio/scan-positions
   ```
   Expect `status: "complete"` with `overkill.alerts_created` and `contrarian.alerts_created` counts.
3. Verify the read-only aggregator still works:
   ```bash
   curl http://localhost:8006/api/portfolio/positions-intelligence | jq '.total, .positions | keys[:5]'
   ```
4. Confirm alerts surfaced in Alert Hub for any high-score held position:
   ```bash
   curl "http://localhost:8006/api/alert-hub/alerts?source=OVERKILL&active=true" | jq '.alerts | length'
   ```

### Frontend (after Vite HMR — no restart needed)
1. Visit http://localhost:5420/portfolio
2. Confirm the new **"Stocks & CCs"** sub-tab appears next to Options / Opportunities / Simulator. Click it — the full StocksWithCCTable should render with the Signals column populated by `PositionSignalsCell`.
3. Click the **Options** sub-tab. For every grouped underlying header (e.g. `MSFT`, `AAPL`), verify a row of scanner badges (OK / CT / Alerts / CSP / OPP / ER) appears next to the symbol — the same component as on the stocks table.
4. Click the **"Scan Positions"** button inside the Stocks & CCs tab. After ~5–15 seconds the badges should refresh and `useScanPositions().mutate()` invalidates `['portfolio', 'positions-intelligence']` and `['alert-hub']` so both views update.
5. Confirm the previously-collapsed `<details>` element is gone (no duplicate Stocks section).
6. Run the playwright smoke test:
   ```bash
   python .claude/skills/playwright-testing/runner.py smoke http://localhost:5420/portfolio
   ```
   Expect `"status": "success"`.

### End-to-End Auto-Alert Flow
1. Wait for the next scheduled scan window (or trigger via the curl above).
2. Open `/alert-hub` and filter by source = `OVERKILL` or `CONTRARIAN`.
3. Any held stock with composite score ≥70 (Overkill) or ≥65 (Contrarian) should appear as a new alert with the position symbol and a `scanned_at` timestamp matching the scheduled run.
