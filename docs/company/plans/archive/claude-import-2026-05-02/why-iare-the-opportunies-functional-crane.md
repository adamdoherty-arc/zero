# Trade Planner & Opportunities Enhancement Plan

## Context

The user is experiencing blank opportunities in the portfolio interface and wants to improve the trade planner based on new features that have been added to the platform, including new news sources. Through investigation, I've identified both immediate fixes needed and substantial enhancement opportunities.

## Phase 1: Fix Blank Opportunities Issue (Critical)

### Problem Identified
**Root Cause**: The "Opportunities" tab in `TodayCommandCenter.tsx` is displaying `recommendationAlerts` (AI trading recommendations) instead of position opportunities. When there are no AI recommendations, users see "No Opportunities" with a "Run Scanner" button that doesn't help.

**Current Wrong Flow**: Portfolio → TodayCommandCenter → Opportunities Tab → recommendationAlerts (empty) → "No Opportunities"

**Correct Flow Should Be**: Portfolio → TodayCommandCenter → Opportunities Tab → Position opportunities (CSP alternatives, CC rolls, stock CC opportunities)

### Files to Modify
1. `frontend/src/components/planner/TodayCommandCenter.tsx` (line 254)
2. `frontend/src/hooks/useTodayCommandCenter.ts` 
3. Add data fetching for position opportunities

### Solution
- Wire opportunities tab to use `usePositionOpportunities()` hook instead of recommendation alerts
- Add position opportunities data fetching to `useTodayCommandCenter()` hook  
- Use existing position opportunities API endpoints (`/api/position-opportunities/all`)
- Display CSP alternatives, CC rolls, and stock CC opportunities that are already being scanned every 15 minutes

## Phase 2: News Integration in Trade Planning

### News Sources Available
**Current News Infrastructure** (Sprint 178):
- Multi-source news aggregator with Alpaca News API (primary), Finnhub (fallback), Polygon (sentiment)
- News Hub router with comprehensive endpoints
- Watchlist-specific and market-wide news
- Sentiment scoring and deduplication
- 5-minute caching for performance

### Integration Points
1. **Daily Dashboard Enhancement**
   - Add "Market Intelligence" card showing top 3-5 news items for watchlist symbols
   - Display sentiment alignment with trading recommendations
   - Show news-driven catalysts for recommended trades

2. **Recommendation Context**
   - Enhance `RecommendationCard.tsx` with news catalyst badges
   - Show sentiment alignment ("News sentiment: Bullish + CSP recommendation = High confidence")
   - Surface whether news supports or conflicts with strategy

3. **Weekly Strategic Plan News Context**
   - Add market context section with earnings announcements and macro events
   - Integrate news sentiment trends into weekly theme determination

## Phase 3: Market Intelligence Integration

### Available But Not Integrated
**Flow Intelligence** (`/api/flow-intelligence/`):
- Dark pool activity, options flow alerts, GEX regime, 0DTE levels
- NOPE calculations, whale activity tracking
- Signal confidence thresholds and deduplication

**Macro Calendar** (`/api/macro-calendar/`):
- Economic events with impact analysis
- Historical market reactions to events

**Whale Tracking** (`/api/prediction-whales/`):
- Whale consensus and positioning data
- Smart money view on market direction

### Integration Strategy
1. **Enhanced Daily Plan Data**
   - Extend `DailyPlan` dataclass to include market intelligence
   - Add parallel data fetching for news, macro events, flow alerts
   - Display in dedicated market intelligence widget

2. **Options Strategy Enhancement**
   - Show GEX regime context for options recommendations
   - Display 0DTE levels for intraday positioning
   - Add options flow confirmation for strategy recommendations

3. **Recovery Plan Intelligence**
   - Add news sentiment context for understanding losses
   - Include whale consensus on recovery trade ideas
   - Show macro calendar impact on recovery timeline

## Phase 4: LangGraph Agent Integration

### Available LangGraph Components
- Portfolio Advisor Agent, Alert Lifecycle Agent
- CSP Scoring agents, Swarm Orchestrator
- Signal Gateway with confidence scoring

### Integration Opportunities
1. **Daily Plan Reasoning Agent**
   - Create LangGraph agent for comprehensive daily plan generation
   - Add reasoning chain: portfolio state → market regime → alerts → recommendations
   - Expose plan reasoning narrative to users

2. **Plan Quality Scoring**
   - Implement LangGraph agent for 0-100 daily plan scoring
   - Evaluate recommendations vs market conditions, risk exposure, optimization
   - Display quality score prominently with improvement suggestions

3. **Position Action Intelligence**
   - Use LangGraph for enhanced HOLD/ROLL/CLOSE/DEFEND decisions
   - Integrate with options flow and whale consensus for confirmation
   - Provide confidence scores for each position action

## Implementation Priorities

### High-Value, Low-Effort (Week 1)
1. **Fix opportunities tab data source** (Critical fix)
2. **Add macro calendar events to DayDashboard** (API exists, needs UI)
3. **Show news headlines in recommendation cards** (API exists, needs integration)

### Medium-Value, Medium-Effort (Week 2-3)
1. **Market intelligence card in DayDashboard** (multiple data sources)
2. **News sentiment in weekly strategic plans** (requires service modifications)
3. **Options flow confirmation badges** (backend dataclass extension needed)

### High-Value, High-Effort (Week 4+)
1. **LangGraph-powered daily planning agent** (new agent development)
2. **Comprehensive plan quality scoring** (algorithm + UI development)
3. **Full market intelligence integration** (multiple service integrations)

## Critical Files to Modify

### Backend
- `backend/services/daily_planner_service.py` - Add news and market intelligence data gathering
- `backend/services/weekly_strategic_plan_service.py` - Add news context methods
- `backend/routers/daily_planner.py` - Potentially new endpoints for enhanced data

### Frontend  
- `frontend/src/components/planner/TodayCommandCenter.tsx` - Fix opportunities data source + add market intelligence
- `frontend/src/hooks/useTodayCommandCenter.ts` - Add position opportunities and market data fetching
- `frontend/src/components/planner/DayDashboard.tsx` - Add market intelligence card
- `frontend/src/components/planner/RecommendationCard.tsx` - Add news catalyst badges

## Verification Strategy

### Phase 1 Verification
- Opportunities tab shows actual position opportunities (CSP alternatives, CC rolls)
- No more "No Opportunities" when position opportunities exist
- Position opportunities refresh correctly

### Phase 2-4 Verification  
- News sentiment appears in recommendation cards
- Macro events visible in daily dashboard
- Market intelligence data displays correctly
- Weekly plans include news and macro context
- Plan quality scores calculate and display properly

## Expected Outcomes

1. **Immediate Fix**: Users see actual trading opportunities instead of blank screen
2. **Enhanced Context**: Trading decisions informed by news sentiment and market intelligence  
3. **Better Planning**: Daily and weekly plans incorporate comprehensive market data
4. **Improved Confidence**: Signal agreement and confidence scores help validate decisions
5. **Smarter Recommendations**: LangGraph agents provide reasoning and quality assessment

This plan transforms the trade planner from a basic calendar/recommendation system into a comprehensive intelligence-driven planning platform leveraging all available market data sources.