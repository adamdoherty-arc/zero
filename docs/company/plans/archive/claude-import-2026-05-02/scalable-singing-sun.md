# Platform Audit Fix Plan — All 37 Features → 100/100

## Context

Platform audit completed 2026-04-03. Current platform grade: 76.5/100 (C+).
1 F, 4 D's, 6 C-'s. No features above B+. Goal: bring ALL 37 features to 100.

Exploration revealed several audit miscalculations — some "dead" features actually have full backends (ETF Hub, Feature Quality, News). Fixes are organized into 7 waves by effort and dependency order.

---

## Wave 1: Dead Feature Resurrection (ETF Hub priority)

### 1a. ETF Hub — Register Router in main.py
**Problem**: Backend router `backend/routers/etf_hub.py` exists with 7 endpoints but is NOT registered in `backend/main.py`. Frontend 130 LOC shell with 5 lazy tabs.
**Fix**:
- Add `from backend.routers import etf_hub` + `app.include_router(etf_hub.router)` in `backend/main.py`
- Verify `etfs_universe` DB table exists (run `\d etfs_universe` via psql)
- If table missing: create migration with indexes
- Curl all 7 endpoints after restart to verify
- **Files**: `backend/main.py`, possibly `backend/infrastructure/database_migrations.py`
- **Score lift**: D2 70→90 (+20), overall 78→88

### 1b. Feature Quality — Verify Router Registration
**Problem**: Backend `backend/routers/feature_quality.py` has 6 endpoints + `backend/services/feature_quality_service.py` exists. May already be registered (search main.py for `feature_quality`).
**Fix**:
- Verify registration in main.py. If missing, add it.
- Curl `/api/quality/scorecard` to verify data returns
- Verify frontend hook fetches from correct endpoint
- **Files**: `backend/main.py`, `frontend/src/pages/FeatureQualityDashboard.tsx`
- **Score lift**: D2 40→85 (+45), overall 68.8→85

### 1c. Documentation — Fix fetch() and Verify Content
**Problem**: Uses `fetch()` instead of `axiosInstance`. Only 3/30 pages have content, but has hardcoded fallback content for key pages.
**Fix**:
- Replace `fetch()` with `axiosInstance` in DocumentationHub.tsx
- Verify backend router exists and serves markdown
- Trim navigation tree to only show pages with actual content (remove empty stubs)
- **Files**: `frontend/src/pages/DocumentationHub.tsx`
- **Score lift**: D1 60→80, D2 25→70, overall 53.3→72

---

## Wave 2: Quick Fixes (S effort, big D2/D1 lifts)

### 2a. Agent Dashboard — Remove Hardcoded Fake Data
**Problem**: Lines ~357-361 have hardcoded `"0.82"` sentiment and `"Low"` risk.
**Fix**: Replace with data from WebSocket `market_context` (which already sends `regime`, `vix`, `fear_greed`). Use `fear_greed/100` for sentiment, derive risk from VIX thresholds.
- **Files**: `frontend/src/pages/AgentDashboard.tsx`
- **Score lift**: D2 35→70 (+35), overall 68→78

### 2b. System Hub — Wire Dead Diagnostics Button
**Problem**: "Run Diagnostics" button has no `onClick` handler.
**Fix**: Wire to `POST /api/system/diagnostics` or `/api/cos/run-probes`.
- **Files**: `frontend/src/pages/SystemHub.tsx`
- **Score lift**: D1 82→88

### 2c. Advisor Track Record — Add AIErrorBoundary + Error Handling
**Problem**: Only feature missing `AIErrorBoundary`. No `isError` handling.
**Fix**: Wrap page content in `<AIErrorBoundary>`. Add `isError` display. Add equity curve chart (recharts Line), SPY benchmark comparison.
- **Files**: `frontend/src/pages/AdvisorTrackRecord.tsx`
- **Score lift**: D4 75→90, D6 78→88, overall 71.4→82

### 2d. IPO Calendar — Add Symbol Deep-Links + Skeleton
**Problem**: IPO symbols don't link to Stock Detail. No skeleton loaders.
**Fix**: Add `onClick={() => navigate(`/stocks/detail/${symbol}`)}` to symbol cells. Add skeleton loading state.
- **Files**: `frontend/src/pages/IPOHub.tsx`
- **Score lift**: D3 72→85, D4 78→88, overall 75.2→82

### 2e. News — Score Re-evaluation
**Problem**: Audit scored 63.6 but exploration found it's FULLY IMPLEMENTED (aggregator, sentiment, trending). Backend was down during audit.
**Fix**: Re-verify endpoints work. Add symbol deep-links to Stock Detail from trending symbols. Add AI summarization hook. Add `navigate()` to earnings calendar items.
- **Files**: `frontend/src/pages/NewsHub.tsx`
- **Score lift**: D2 55→85, D3 55→75, D6 45→70, overall 63.6→80

---

## Wave 3: Monolithic File Splitting (D5 boost across 10 features)

Split inline tab components into separate files following existing patterns (e.g., `stock-detail/tabs/` directory). Each split follows the same pattern:
1. Create `components/{feature}/` directory
2. Extract each tab's inline component into its own file
3. Export from `index.ts`
4. Import in parent page (lazy where >200 LOC)

### Files to Split

| File | LOC | Tabs | Target Dir | Components to Extract |
|------|-----|------|------------|----------------------|
| `QADashboard.tsx` | 3119 | 5 | `components/qa/` | OverviewTab, IssuesTab, RunHistoryTab, HotSpotsTab, AIAssistantTab, CardSkeleton |
| `AlertHub.tsx` | 2614 | 10 | `components/alert-hub/` | DashboardTab, AIAdvisorTab, CSPTab, EarningsTab, PredictionTab, HistoryTab, FilterPill, StatCard |
| `EarningsIntelligenceHub.tsx` | 2306 | 9 | `components/earnings/` | CalendarTab, AlertsTab, EPRTab, IVCrushTab, RecoveryTab, HeatmapTab, JournalTab, PreviewTab |
| `ChartAnalysisHub.tsx` | 2273 | panels | `components/chart/` | CompactChartPanel, IndicatorPanel, DrawingToolbar, LayoutSelector, TimeframeBar |
| `Settings.tsx` | 2104 | 10 | `components/settings/` | ConnectionsTab, NotificationsTab, AppearanceTab, SystemTab (4 already extracted: Discord, LLM, DataSources, ExternalAPIs) |
| `PaperTradingHub.tsx` | 2015 | 5 | `components/paper-trading/` | PositionsTab, OrdersTab, SignalsTab, PerformanceTab, SettingsTab |
| `TradeIntelligenceDashboard.tsx` | 1873 | sections | `components/trade-intelligence/` | CalibrationSection, RegimeMatrix, ABTestResults, LearningLoopViz |
| `XTradesSignals.tsx` | 1869 | 7 | Already has `components/xtrades/` | Lazy-load existing tab components |
| `PortfolioHub.tsx` | 1725 | tabs | Already has `components/portfolio/` | Extract remaining inline sections |
| `StockDetailPage.tsx` | 2130 | 9 | Already has `stock-detail/tabs/` | Extract remaining inline helpers |

**Score lift per file**: D5 +15-30 pts each
**Pattern to follow**: `frontend/src/pages/stock-detail/tabs/` (existing best practice)

---

## Wave 4: TOOLS Integration into Stock Detail (D3 boost)

### 4a. Add Comps Tab to Stock Detail
**Current**: Standalone page at `/comps-analysis` with 3 references. Zero inbound links.
**Fix**:
1. Add `'comps'` to `TabType` in `StockDetailTypes.ts`
2. Create `frontend/src/pages/stock-detail/tabs/CompsTab.tsx` — reuse `useCompsAnalysis` hook
3. Add to tabs array + conditional render in StockDetailPage
4. Keep standalone route but add "Open in Stock Detail" link
- **Files**: `StockDetailTypes.ts`, `StockDetailPage.tsx`, new `tabs/CompsTab.tsx`, `CompsAnalysisPage.tsx`
- **Score lift (Comps)**: D3 45→80, overall 72→82

### 4b. Add DCF Tab to Stock Detail
Same pattern as 4a. Reuse `useDCFValuation` hook.
- Add `'dcf'` to TabType, create `tabs/DCFTab.tsx`
- **Score lift (DCF)**: D3 45→80, overall 72.6→82

### 4c. Add Vol Analysis Tab to Stock Detail
Same pattern. Reuse `useVolAnalysis` hook.
- Add `'vol-analysis'` to TabType, create `tabs/VolAnalysisTab.tsx`
- **Score lift (Vol)**: D3 45→80, overall 71.5→82

### 4d. Cross-Link TOOLS from Portfolio
Add navigation links from PortfolioHub to: Rebalancing, Tax Harvesting, Screener.
Add links from Dashboard Quick Actions to all TOOLS.
- **Files**: `PortfolioHub.tsx`, `Dashboard.tsx`
- **Score lift (Rebalancing, TLH, Screener)**: D3 +10-15 each

### 4e. Cross-Link Quant Lab ↔ Risk Dashboard
Add navigation between overlapping features. Deduplicate Kelly Criterion display.
- **Files**: `QuantLabHub.tsx`, `RiskDashboard.tsx`
- **Score lift (Quant)**: D3 68→82

---

## Wave 5: Screener Expansion + UX Polish (D4/D6 boost)

### 5a. Expand Screener Filters (6 → 20+)
**Backend already supports 13+ filters**. Frontend only shows 6.
**Fix**: Add 14 more fields to `FILTER_FIELDS` in `FundamentalScreensPage.tsx`:
```
marketCap_min/max, dividendYield_min, netProfitMargin_min,
freeCashFlowYield_min, payoutRatio_min/max, sector, industry,
currentRatio_min, operatingMargin_min, earningsGrowth_min,
analystRating_min, beta_max
```
Add saved screens (localStorage), collapsible filter groups.
- **Files**: `FundamentalScreensPage.tsx`, `useFundamentalScreens.ts`
- **Score lift**: D1 87→95, D6 60→80

### 5b. Add Skeleton Loaders to 9+ Pages
These pages lack skeleton loading states:
- `AdvisorTrackRecord.tsx`, `IPOHub.tsx`, `QuantLabHub.tsx`, `ETFHub.tsx`
- `CompsAnalysisPage.tsx`, `DCFValuationPage.tsx`, `VolAnalysisPage.tsx`
- `RebalancingPage.tsx`, `FundamentalScreensPage.tsx`
**Pattern**: Use existing `DashboardSkeleton` or create `HubSkeleton` shared component.
- **Score lift**: D4 +5-8 each

### 5c. Add EmptyState Shared Component
Create shared `<EmptyState icon={} title="" description="" action={} />` component.
Adopt across all TOOLS and SYSTEM pages for consistency.
- **Files**: New `frontend/src/components/shared/EmptyState.tsx`, update 15+ pages
- **Score lift**: D4 +3-5 each

---

## Wave 6: Competitive Edge Enhancements (D6 boost)

### 6a. Add Chart Visualizations to TOOLS
- **Vol Analysis**: Replace table IV Surface with Recharts heatmap. Add term structure line chart.
- **DCF**: Add revenue projection bar chart. Interactive sensitivity heatmap (color-coded cells).
- **Rebalancing**: Add current vs target donut chart (Recharts PieChart).
- **Files**: `VolAnalysisPage.tsx`, `DCFValuationPage.tsx`, `RebalancingPage.tsx`
- **Score lift**: D6 +15-20 each

### 6b. DCF Editable Assumptions
Add sliders for growth rate, discount rate, terminal growth with live recalculation.
- **Files**: `DCFValuationPage.tsx`, `useDCFValuation.ts`
- **Score lift**: D1 87→95, D6 65→85

### 6c. Rebalancing + TLH Execution Integration
Wire to existing `TradierService` (backend/services/execution/tradier_service.py):
- Add `POST /api/portfolio-optimization/execute` endpoint
- Add `POST /api/portfolio/tlh/execute` endpoint
- Add "Execute Plan" button with confirmation dialog + dry-run preview
- **Files**: `portfolio_optimization.py` (router), `tlh_workflow.py` (router), `RebalancingPage.tsx`, `TLHWorkflowPage.tsx`
- **Score lift**: D1 +5, D6 +15 each

### 6d. News AI Summarization
Add endpoint `POST /api/research/news/summarize` using LLM router.
Add "AI Summary" button per article. Add "Market Brief" auto-summary.
- **Files**: `news_hub.py` (router), `NewsHub.tsx`
- **Score lift**: D6 45→75

### 6e. Sprint Manager — Add Completion Workflow + Burndown
Add "Complete Sprint" button, burndown chart, velocity metrics.
- **Files**: `SprintManagerHub.tsx`
- **Score lift**: D1 88→95, D6 82→90

---

## Wave 7: Final Polish & System Coherence

### 7a. API Response Envelope Standardization
Create middleware or utility wrapper for consistent `{data, meta, errors}` envelope.
Apply to 10 highest-traffic endpoints first.
- **Files**: `backend/infrastructure/response_envelope.py` (new), update 10 routers

### 7b. Documentation Auto-Generation
Generate docs from topic files (``.claude/memory/topics/*.md``) into Documentation page.
Trim nav tree to only populated pages.
- **Files**: `DocumentationHub.tsx`, possibly `backend/routers/documentation.py`

### 7c. Strategy Scanner → Advisor Pipeline
Wire scanner output to `unified_ai_advisor.py` consumption. Currently write-only.
- **Files**: `unified_ai_advisor.py`, `strategy_scanner_service.py`

### 7d. Fear & Greed Source Fix
Replace crypto-based alternative.me with stock market F&G (CNN index or custom VIX+breadth+put-call composite).
- **Files**: `backend/services/market_regime_agent.py` or relevant sentiment service

### 7e. Fix API Endpoint Path Mismatches
4 frontend/backend prefix mismatches found:
- `/api/alert-hub/summary` → actual: `/api/alert-hub/stats`
- `/api/market/overview` → actual: `/api/market/indices`
- `/api/qa/latest` → actual: `/api/qa/status`
- `/api/smart-rules/rules` → actual: `/api/rules/*`
Fix frontend hooks to use correct paths.

---

## Execution Order & Parallelization

| Wave | Tasks | Parallel? | Est. Time | Score Impact |
|------|-------|-----------|-----------|-------------|
| **1** | ETF Hub + Feature Quality + Documentation | 3 parallel subagents | 10 min | +3 features from D→B |
| **2** | Agent Dashboard + System Hub + Advisor Track Record + IPO + News | 3 parallel subagents | 15 min | +5 features from C/D→B |
| **3** | Split 10 monolithic files | 3 parallel subagents (3-4 files each) | 30 min | D5 +15-30 across 10 features |
| **4** | TOOLS→StockDetail integration + cross-links | 2 parallel subagents | 20 min | D3 +20-35 across 8 features |
| **5** | Screener expansion + skeleton loaders + EmptyState | 2 parallel subagents | 15 min | D4/D6 +5-15 across 15 features |
| **6** | Chart viz + editable assumptions + execution wiring | 3 parallel subagents | 25 min | D6 +15-25 across 8 features |
| **7** | API consistency + docs gen + pipeline fixes | 2 parallel subagents | 20 min | Coherence PARTIAL→PASS |

**Total estimated**: ~2-3 hours of parallel execution

---

## Verification

After each wave, run targeted checks:
- `curl` all fixed endpoints to confirm 200 + real data
- `docker restart ada-backend` after any Python changes
- Grep fixed pages for remaining TODOs/placeholders
- Run `/platform-auditor --quick` after final wave to validate all scores

**Target**: All 37 features at 90+ (A- or better). Perfect 100 requires live data verification which depends on market hours and API key availability.

---

## Critical Files Reference

### Frontend
- `frontend/src/App.tsx` — Route definitions
- `frontend/src/pages/StockDetailPage.tsx` — Tab system for TOOLS integration
- `frontend/src/pages/stock-detail/StockDetailTypes.ts` — TabType union
- `frontend/src/pages/stock-detail/tabs/` — Tab component pattern to follow

### Backend
- `backend/main.py` — Router registrations (ETF Hub, Feature Quality)
- `backend/routers/etf_hub.py` — 7 endpoints (needs registration)
- `backend/routers/feature_quality.py` — 6 endpoints (verify registration)
- `backend/services/execution/tradier_service.py` — Broker execution (for rebal/TLH)

### Patterns to Reuse
- `AIErrorBoundary` from `@/components/shared` — wrap all pages
- `DashboardSkeleton` pattern — skeleton loading
- `stock-detail/tabs/` pattern — tab extraction
- `useNavigate()` + `?tab=` params — cross-linking
