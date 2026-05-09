# Platform Auditor - Run 4 Execution Plan

## Context

Last audit (Run 3) was 2026-04-03, scored **79.4/100** (simple) / **80.3/100** (weighted). Since then, 23 commits landed on the sprint branch with:
- **3 new routers**: contrarian_scanner (`/api/scanner/contrarian`), alpha_hypothesis (`/api/alpha-hypotheses`), ipo_calendar (`/api/ipo`)
- **4 new library services**: stock_scoring, unusual_options_scanner, edgar_insider, recovery_plan
- **Major advisor changes**: Scanner context integration (+535 insertions to unified_ai_advisor)
- **Learning system expansion**: 6 commits, ~1000+ insertions (wheel cycle learning, LangGraph tool registry, debate pattern)
- **Response envelope standardization**: New `response_envelope.py` applied to 5 routers + axios interceptor
- **Dead code cleanup**: ~3500 lines removed
- **6 P0/P1 issues** from Run 3 need live re-verification

Feature catalog verified: **37 features** unchanged (no new sidebar entries, no removed routes).

## Execution Strategy

**Mode**: Full audit with emphasis on changed features + P0/P1 re-verification
**Approach**: 7 parallel batches organized by section priority (HUBS first)

### Step 0: Backend Pre-check & Warm-up

1. Health check: `curl -s --max-time 5 http://localhost:8006/api/health`
2. Warm caches with 3 heavy endpoints:
   - `curl -s --max-time 15 http://localhost:8006/api/dashboard/summary`
   - `curl -s --max-time 15 http://localhost:8006/api/portfolio`
   - `curl -s --max-time 15 http://localhost:8006/api/market`
3. Wait 5 seconds, then proceed

### Step 1: P0/P1 Issue Re-verification (Priority)

Test all 6 critical issues from Run 3:

| Issue | Test Command | Pass Criteria |
|-------|-------------|---------------|
| P0: Prediction Markets disabled | `curl -s http://localhost:8006/api/prediction-markets/dashboard` | Non-empty, no `_service_disabled` |
| P0: Chart signals symbol parsing | `curl -s "http://localhost:8006/api/chart-data/signals?symbol=AAPL"` | Valid signal data for AAPL |
| P0: Scanner /scan timeout | `curl -s --max-time 30 http://localhost:8006/api/multi-strategy-scanner/strategies/momentum/scan` | Response within 30s |
| P1: Advisor Track Record zeros | `curl -s http://localhost:8006/api/evaluation/track-record` | Non-zero win_rate/total_trades |
| P1: News empty array | `curl -s http://localhost:8006/api/research/news` | Non-empty news array |
| P1: Vol Analysis 500 | `curl -s http://localhost:8006/api/vol-analysis/surface/AAPL` | HTTP 200 with data |

### Step 2: New Feature Audit (3 features)

**Contrarian Scanner** — sub-feature of Premiums Scanner (/scanner)
- Router: `backend/routers/contrarian_scanner.py`
- Service: `backend/services/contrarian_scanner_service.py`
- Frontend: `frontend/src/components/scanner/ContrarianTab.tsx`, `ContrarianDetailModal.tsx`
- Test endpoints: `POST /api/scanner/contrarian/scan`, `GET /api/scanner/contrarian/top`
- DB: `contrarian_scan_results` table
- Grade as sub-feature of premiums_scanner (improves D1/D2/D6)

**Alpha Hypothesis** — no frontend yet, router-only
- Router: `backend/routers/alpha_hypothesis.py`
- Service: `backend/services/alpha_hypothesis_service.py`
- Test endpoints: `GET /api/alpha-hypotheses/`, `GET /api/alpha-hypotheses/summary/stats`
- No frontend page — impacts D1 (partial), D3 (low integration)
- Grade as standalone or note as "backend-only, no UI exposure"

**IPO Calendar** — already in catalog from Run 3, but verify new router
- Router: `backend/routers/ipo_calendar.py` (new file)
- Service: `backend/services/ipo_calendar_service.py` (new file)
- Frontend: `frontend/src/pages/IPOHub.tsx`
- Test endpoints: `GET /api/ipo/upcoming`, `GET /api/ipo/recent`, `GET /api/ipo/lockup-calendar`, `GET /api/ipo/theta-opportunities`
- Hooks: `frontend/src/hooks/api/useIPOApi.ts`
- Re-audit with new backend (Run 3 scored 79.4 C+)

### Step 3: Full Feature Audit (7 parallel batches)

Launch 7 parallel Task agents, each auditing a batch of features across all 6 dimensions.

**Batch 1 - HOME (2 features)**:
- Dashboard (`/`), Ask ADA (`/ask-ada`)

**Batch 2 - HUBS High-Priority (5 features)**:
- Trade Planner, Portfolio, Alert Hub, Premiums Scanner, Earnings Intelligence

**Batch 3 - HUBS Mid-Priority A (5 features)**:
- XTrades, Stock Detail, Chart Analysis, Whale Intelligence, Options Intelligence

**Batch 4 - HUBS Mid-Priority B (6 features)**:
- Trade Intelligence, Advisor Track Record, Paper Trading, Rules, News, Markets

**Batch 5 - HUBS Low-Priority + New (5 features)**:
- ETF Hub, Prediction Markets, Quant Lab, IPO Calendar, Contrarian (sub-feature)

**Batch 6 - TOOLS (6 features)**:
- Comps Analysis, DCF Valuation, Vol Analysis, Rebalancing, Tax Harvesting, Screener

**Batch 7 - SYSTEM (9 features)**:
- System Hub, Sprint Manager, Agent Dashboard, Orchestration Manager, QA Dashboard, Feature Quality, Enhancement, Documentation, Settings

Each batch agent will:
1. Test primary API endpoints via curl (D2: Data Quality)
2. Check frontend page files for completeness markers (D1: Functional)
3. Check integration links (D3: Integration via grep for inbound/outbound links)
4. Check UX patterns (D4: Loading states, error handling, responsive classes)
5. Check code quality (D5: File sizes, TODOs, bare excepts, print statements)
6. Compare to competitive baselines (D6: from competitive_baselines.json)
7. Return per-feature scores for all 6 dimensions

### Step 4: System Coherence Checks

After all batch agents return:

**4a. Data Flow Integrity** — Trace the signal pipeline:
```
Signal Gen (Scanner, XTrades, Flow) → Analysis (Advisor, Conviction, LangGraph)
→ Recommendation (Planner, Proactive, Alerts) → Execution (Paper, Broker)
→ Evaluation (Learning, Track Record)
```
Verify scanner→advisor integration (new in this sprint).

**4b. API Consistency** — Sample 10 endpoints:
- Check response envelope adoption (5 routers now use it)
- Check error format consistency
- Check naming conventions

**4c. UX Consistency** — Verify across 5+ pages:
- Error boundary coverage (83/83 from Run 3)
- Loading patterns, empty states

**4d. Duplication Detection** — Re-check known pairs:
- Quant Lab vs Risk Dashboard (40% overlap, cross-linked)
- Alert Rules vs Smart Rules (25% overlap, monitoring)
- Any new overlaps from contrarian scanner vs existing scanners

**4e. Dead Feature Detection** — Re-check from Run 3:
- Prediction Markets (was disabled)
- Documentation (was F-grade shell)
- Comps/DCF (data pipeline broken)
- Vol Analysis (HTTP 500)

### Step 5: Scoring & Report Generation

1. Calculate weighted scores per feature using dimension weights
2. Generate full scorecard (ranked worst-first)
3. Top 10 highest-impact improvements
4. Trend comparison vs Run 3
5. Duplication report
6. Dead feature report
7. System coherence summary

### Step 6: Update Knowledge Files

1. Append Run 4 to `audit_history.json` (prune to last 20 runs)
2. Update `feature_catalog.json` — add contrarian scanner, alpha hypothesis if needed
3. Update `dead_features.json` — resolve or flag based on P0/P1 results
4. Update `duplication_registry.json` if new overlaps found
5. Update `improvement_patterns.md` with which Run 3 recommendations were acted on

## Key Files to Modify (knowledge files only)

- `.claude/skills/platform-auditor/knowledge/audit_history.json`
- `.claude/skills/platform-auditor/knowledge/feature_catalog.json`
- `.claude/skills/platform-auditor/knowledge/dead_features.json`
- `.claude/skills/platform-auditor/knowledge/duplication_registry.json`
- `.claude/skills/platform-auditor/knowledge/improvement_patterns.md`

## Verification

1. All 37 features have scores across 6 dimensions
2. All P0/P1 issues have live test results
3. New features (contrarian, alpha hypothesis, ipo) are graded
4. System coherence checks completed
5. Knowledge files updated with Run 4 data
6. Report shows trend vs Run 3 (improving/declining per feature)

## Estimated Execution

- Step 0 (warm-up): ~30 seconds
- Step 1 (P0/P1): ~2 minutes
- Step 2 (new features): ~3 minutes
- Step 3 (7 parallel batches): ~10-15 minutes
- Step 4 (coherence): ~5 minutes
- Step 5 (report): ~3 minutes
- Step 6 (knowledge update): ~2 minutes
- **Total**: ~25-30 minutes
