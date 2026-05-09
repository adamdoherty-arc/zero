# Plan: Streamline Scanner → Alert Pipeline (Make ADA Fully Autonomous)

## Context

ADA has 6+ scanners but only 3 are auto-scheduled. The rest require manual triggering, which defeats the purpose of an agentic financial advisor. Worse, the overkill scanner's scheduled task has a **critical bug** (passes `symbols=[]` which returns empty — it's been a no-op since it was created). The contrarian scanner has no scheduling at all and no DB persistence table. The StrategyScannerHub page requires clicking "Scan" to see results.

**Goal**: Every scanner runs autonomously on a schedule, all results flow to Alert Hub, and the UI shows auto-scanned results on page load.

---

## Phase 1: Fix Overkill Scanner (Critical Bug)

**Problem**: [scheduled_tasks.py:1570](backend/services/scheduled_tasks.py#L1570) calls `scan_symbols(symbols=[])` but [overkill_bounce_scanner_service.py:450](backend/services/overkill_bounce_scanner_service.py#L450) returns `[]` when symbols is empty. The universe-fetching logic lives only in the router at [overkill_bounce_scanner.py:195](backend/routers/overkill_bounce_scanner.py#L195).

**Fix**:
1. Move `_get_default_universe()` from the router into `OverkillBounceScannerService` as a method
2. Update `scan_symbols()` — when `symbols=[]`, auto-fetch from `get_default_universe()` instead of returning empty
3. Update router to call `service.get_default_universe()` instead of the local helper
4. Keep scheduled task code as-is (it already passes `symbols=[]`, which will now trigger auto-fetch)

**Files**:
- `backend/services/overkill_bounce_scanner_service.py` — add `get_default_universe()`, fix `scan_symbols()`
- `backend/routers/overkill_bounce_scanner.py` — update to use `service.get_default_universe()`

---

## Phase 2: Schedule Contrarian Scanner + Add DB Persistence

**Problem**: Contrarian scanner is manual-only. It pushes to `real_time_alerts` but has no `contrarian_scan_results` table (the `alert_rule_engine.py` already queries this table at line 523, but it doesn't exist).

**Fix**:
1. Create Alembic migration for `contrarian_scan_results` table (mirror `overkill_scan_results` structure)
   - Columns: id, symbol, composite_score, grade, recommendation, confidence, price, low_52w, pct_off_low, volume_ratio, rsi, factors (JSONB), suggested_entry/stop/target, is_active, scanned_at, expires_at
   - Indexes: `(symbol, is_active)`, `(is_active, composite_score DESC)`, `(scanned_at)`
2. Add `_persist_results()` method to contrarian service (copy pattern from [overkill_bounce_scanner_service.py:1427](backend/services/overkill_bounce_scanner_service.py#L1427))
3. Add `get_default_universe()` method to contrarian service (same pattern — query stock_universe)
4. Update `scan_symbols()` — when `symbols=[]`, auto-fetch universe
5. Add `run_contrarian_scan()` to [scheduled_tasks.py](backend/services/scheduled_tasks.py) — every 60 min during market hours
6. Register the cron job in `start_scheduler()`

**Files**:
- `backend/alembic/versions/20260404_contrarian_scan_results.py` — new migration
- `backend/services/contrarian_scanner_service.py` — add persist + universe methods
- `backend/services/scheduled_tasks.py` — add `run_contrarian_scan()` + cron registration

---

## Phase 3: Schedule Multi-Strategy Scanner (CC, Spreads, Condors)

**Problem**: The multi-strategy scanner at [multi_strategy_scanner.py](backend/routers/multi_strategy_scanner.py) only runs when the user clicks "Scan" on the StrategyScannerHub. CSP is already covered by the premium scanner, but covered calls, bull put spreads, and iron condors have no auto-scheduling.

**Fix**:
1. Add `run_strategy_auto_scan()` to scheduled_tasks.py — runs 2x daily (11:00 AM, 3:00 PM ET)
2. Scans top 200 optionable symbols for: covered_call, credit_spread, iron_condor
3. Persists results to existing `strategy_opportunities` table
4. For opportunities scoring >= 75, auto-insert into `real_time_alerts` (source=`options_hub`)
5. Add Alert Hub integration method to `strategy_scanner_service.py`

**Files**:
- `backend/services/strategy_scanner_service.py` — add `_generate_hub_alerts()` method
- `backend/services/scheduled_tasks.py` — add `run_strategy_auto_scan()` + cron registration

---

## Phase 4: StrategyScannerHub Auto-Loads Results

**Problem**: [StrategyScannerHub.tsx:589](frontend/src/pages/StrategyScannerHub.tsx#L589) has `enabled: false` — the page shows nothing until user clicks "Scan".

**Fix**:
1. Change `enabled: false` to `enabled: true` so stored results load on page mount
2. Add a `/api/scanner/strategies/latest` endpoint that returns the most recent auto-scanned results across all strategies
3. Add "Last scanned: X min ago" timestamp display
4. Keep the "Scan" button for manual re-scans, but page shows auto-results by default
5. The Overkill and Contrarian tabs already auto-load (they're separate components) — no changes needed there

**Files**:
- `frontend/src/pages/StrategyScannerHub.tsx` — change enabled, add latest query
- `backend/routers/multi_strategy_scanner.py` — add `GET /strategies/latest` endpoint

---

## Phase 5: Remove Dead Code

1. **Delete** `backend/services/opportunity_scanner_agent.py` — dead code, never started in main.py, fully redundant with premium + multi-strategy scanners
2. **Clean up** any imports referencing the deleted file

**Files**:
- `backend/services/opportunity_scanner_agent.py` — delete
- Check for imports in `backend/main.py`, `backend/services/__init__.py`

---

## After-State: All Scanners Auto-Scheduled

| Scanner | Schedule | Universe | Alert Hub Source |
|---------|----------|----------|-----------------|
| Premium Scanner | 3x daily | 11K optionable | `csp` |
| Chart Scanner | 3x daily | Top 50 liquid | `system` |
| Overkill Bounce | Every 30 min (market hrs) | DB: $1-$50, vol>=500K | `overkill` |
| **Contrarian** | **Every 60 min (market hrs)** | DB: oversold, all prices | `contrarian` |
| **Multi-Strategy** | **2x daily (11am, 3pm)** | Top 200 optionable | `options_hub` |

Zero manual scanning required. All results flow to Alert Hub. StrategyScannerHub shows results on load.

---

## Verification

1. **Overkill fix**: Restart backend → check `docker logs ada-backend --tail 50` for `overkill_bounce_scan_complete` with `total > 0` (was always 0 before)
2. **Contrarian scheduling**: Wait for next 60-min tick → check logs for `contrarian_scan_complete` + query `SELECT count(*) FROM contrarian_scan_results WHERE is_active = true`
3. **Multi-strategy scheduling**: Wait for 11am/3pm tick → check `SELECT count(*) FROM strategy_opportunities WHERE scanned_at > now() - interval '1 hour'`
4. **Frontend**: Navigate to `/strategy-hub` → results should appear without clicking Scan
5. **Alert Hub**: Navigate to `/alert-hub` → filter by source "overkill" / "contrarian" / "options_hub" → should show recent alerts
