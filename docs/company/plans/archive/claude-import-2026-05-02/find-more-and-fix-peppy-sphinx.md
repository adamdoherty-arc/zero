# Plan: Fix settings.json schema + Build Enhanced Daily Report System

## Context

Two work items:

1. **Fix**: `c:\code\ADA\.claude\settings.json` fails to load — the `$schema` URL points at a GitHub raw path but Claude Code validates it against the expected schemastore URL. Result: permission rules + hooks in this file are silently ignored. **ALREADY FIXED** in current session.

2. **Feature**: Build an enhanced **Daily Report** that ADA saves every trading day into the Trade Planner, keyed by date, so the user can scroll back to any day and see a complete advisor-grade picture. **Key discovery**: there's already a mature `DailyBriefing` system with scheduler, dataclass, database table, and API endpoints. The plan is to **extend** this existing infrastructure rather than building parallel systems.

---

## Part 1 — Fix settings.json schema ✅ COMPLETE

**File**: [.claude/settings.json](c:\code\ADA\.claude\settings.json#L2)

**Status**: Already updated in current session. Schema URL changed from GitHub raw to schemastore.

**Verification needed**: Check that VS Code no longer shows yellow toast after reload.

---

## Part 2 — Enhanced Daily Report System (extending existing DailyBriefing)

### Current Infrastructure Analysis

**Existing components found**:
- ✅ `backend/services/daily_briefing_scheduler.py` — mature scheduler with `DailyBriefing` dataclass
- ✅ `backend/routers/briefings.py` — API endpoints for briefings  
- ✅ `backend/infrastructure/proactive_schema.sql` — `daily_briefings` table with JSONB columns
- ✅ `DailyBriefing` dataclass — market_regime, vix_level, portfolio data, top_opportunities, etc.

**Integration strategy**: Extend the existing `DailyBriefing` dataclass and scheduler rather than creating parallel systems. This ensures consistency and leverages working infrastructure.

### 2.1 Database Schema — extend existing `daily_briefings` table

The table already exists with most needed columns:
- `briefing_date DATE UNIQUE` ✅
- `market_regime`, `vix_level`, `top_opportunities JSONB` ✅ 
- `portfolio_health_score`, `risk_alerts JSONB` ✅
- `earnings_calendar JSONB`, `key_insights TEXT[]` ✅

**Migration needed** — `backend/infrastructure/migrations/NNNN_enhanced_daily_report.sql`:

```sql
-- Add enhanced daily report columns to existing daily_briefings table
ALTER TABLE daily_briefings 
  ADD COLUMN IF NOT EXISTS portfolio_snapshot      JSONB,      -- detailed equity, Greeks, positions
  ADD COLUMN IF NOT EXISTS portfolio_advisor_out   JSONB,      -- portfolio_advisor.py LangGraph output
  ADD COLUMN IF NOT EXISTS scanner_highlights      JSONB,      -- {overkill:[], contrarian:[], csp:[], etc}
  ADD COLUMN IF NOT EXISTS indicator_summary       JSONB,      -- chart analysis signals
  ADD COLUMN IF NOT EXISTS related_news            JSONB,      -- portfolio + watchlist news w/ sentiment  
  ADD COLUMN IF NOT EXISTS related_symbols         JSONB,      -- "you like X, also look at Y" recommendations
  ADD COLUMN IF NOT EXISTS alerts_top              JSONB,      -- top N alerts fired today, ranked
  ADD COLUMN IF NOT EXISTS learning_insights       JSONB,      -- learning algorithm day summary
  ADD COLUMN IF NOT EXISTS theta_advisor           JSONB,      -- ADA theta optimizer performance
  ADD COLUMN IF NOT EXISTS ai_narrative            TEXT,       -- long-form advisor commentary
  ADD COLUMN IF NOT EXISTS report_version          INT DEFAULT 1;

-- Index for date-based queries (if not exists)
CREATE INDEX IF NOT EXISTS idx_daily_briefings_date_desc ON daily_briefings (briefing_date DESC);
```

### 2.2 Enhanced DailyBriefing dataclass

**Extend existing**: `backend/services/daily_briefing_scheduler.py`

Add new fields to the `DailyBriefing` dataclass:
- `portfolio_snapshot: dict` — detailed positions, Greeks, equity breakdown
- `portfolio_advisor_out: dict` — LangGraph portfolio advisor recommendations  
- `scanner_highlights: dict` — results from 8+ scanner services
- `indicator_summary: dict` — chart analysis top signals
- `related_news: list` — portfolio/watchlist news with sentiment
- `related_symbols: list` — high-premium recommendations in same sectors
- `alerts_top: list` — top-ranked alerts fired today
- `learning_insights: dict` — patterns, win-rates, confidence calibration
- `theta_advisor: dict` — ADA theta performance summary
- `ai_narrative: str` — long-form advisor commentary

### 2.3 Enhanced DailyBriefingScheduler

**Modify existing**: `backend/services/daily_briefing_scheduler.py`

Add new async methods to `DailyBriefingScheduler`:
- `_gather_portfolio_advisor()` → invoke LangGraph portfolio advisor
- `_gather_scanner_highlights()` → fan-out to existing scanner services
- `_gather_indicator_summary()` → aggregate chart analysis signals  
- `_gather_related_news()` → call existing news aggregator filtered to holdings
- `_gather_related_symbols()` → sector/beta-based premium recommendations
- `_gather_alerts_top()` → query alert_hub for today's top-ranked alerts
- `_gather_learning_insights()` → call learning_insights_service daily summary
- `_gather_theta_advisor()` → ADA theta advisor performance data
- `_generate_ai_narrative()` → LLM synthesis via llm_router (MiniMax M2.7)

Update `generate_briefing()` to call these new gatherers with `asyncio.gather(..., return_exceptions=True)` for resilient fan-out.

### 2.4 API Extensions

**Extend existing**: `backend/routers/briefings.py`

Add new endpoints to existing router:
- `GET /api/briefings/enhanced/{date}` — fetch full enhanced report for date
- `GET /api/briefings/enhanced/range?from=&to=` — date range for calendar
- `POST /api/briefings/enhanced/{date}/regenerate` — manual enhanced report generation
- `GET /api/briefings/enhanced/{date}/export` — markdown/PDF export

Keep existing `/api/briefings/` endpoints unchanged for backward compatibility.

### 2.5 Frontend — Trade Planner Integration

**Modify**: `frontend/src/pages/TradePlannerHub.tsx` — add "Daily Reports" tab

**New files**:
- `frontend/src/hooks/useEnhancedDailyReport.ts` — React Query v5 hooks
- `frontend/src/components/trade-planner/DailyReportView.tsx` — report display with sections
- `frontend/src/components/trade-planner/DailyReportCalendar.tsx` — date picker with report availability dots

Use existing `frontend/src/components/ui/` components for consistency.

### 2.6 RAG Integration 

**New file**: `backend/services/daily_report_rag_indexer.py`

Hook into enhanced briefing generation success → index to new Qdrant collection `daily_reports_enhanced`.
Vector payload: `{date, symbols, strategies, regime, learning_patterns, narrative}`.

Enables semantic queries via ADA Brain: *"show me days when we were bullish on energy with high VIX"*.

### 2.7 Learning Algorithm Integration

Two-way integration:
- **Into report**: `learning_insights_service.get_daily_summary(date)` → learning_insights JSONB
- **From report**: post-market learning loop feeds outcome_learning_service with morning recommendations vs EOD results

### 2.8 Scheduling Strategy

**Two complementary schedules**:
1. **8:00 AM**: Existing lightweight briefing continues (fast morning summary)
2. **5:30 PM**: New enhanced report generation (comprehensive post-market analysis)

Both use same `daily_briefings` table but 5:30 PM job populates the enhanced columns.

---

## Critical Files to Modify/Create

**Modify**:
- `backend/services/daily_briefing_scheduler.py` — extend DailyBriefing dataclass + add enhanced generation methods
- `backend/routers/briefings.py` — add enhanced report endpoints  
- `frontend/src/pages/TradePlannerHub.tsx` — add Daily Reports tab
- `backend/main.py` — register enhanced scheduler alongside existing one

**Create**:
- `backend/infrastructure/migrations/NNNN_enhanced_daily_report.sql` — table extension
- `backend/services/daily_report_rag_indexer.py` — RAG indexing
- `frontend/src/hooks/useEnhancedDailyReport.ts` — React Query hooks
- `frontend/src/components/trade-planner/DailyReportView.tsx` — report UI
- `frontend/src/components/trade-planner/DailyReportCalendar.tsx` — calendar UI
- `backend/tests/test_enhanced_daily_briefing.py` — test coverage
- `.claude/memory/topics/daily-report.md` — documentation

**Work in feature branch**: `feature/enhanced-daily-reports` to avoid conflicts with uncommitted changes.

---

## Verification

1. **Schema**: `\d daily_briefings` shows new enhanced columns
2. **Data generation**: Enhanced briefing populates all new JSONB fields
3. **API**: `GET /api/briefings/enhanced/2026-04-21` returns full enhanced data
4. **Frontend**: Trade Planner → Daily Reports tab → calendar → click date → report renders
5. **RAG**: Enhanced reports indexed in Qdrant, searchable via ADA Brain
6. **Learning**: Post-market learning loop closes with recommendation outcomes

---

## Implementation Approach

Given uncommitted files from recent work, this implementation will:

1. **Work in feature branch** to avoid conflicts
2. **Commit schema fix separately** (already done)  
3. **Extend existing mature briefing system** rather than building parallel infrastructure
4. **Use magnus-database skill** for migration + indexing
5. **Use magnus-api skill** for FastAPI patterns
6. **Use magnus-hooks skill** for React Query v5 patterns
7. **Test incrementally** — backend first, then frontend, then end-to-end

This approach leverages the existing robust daily briefing foundation while adding the comprehensive reporting capabilities requested.