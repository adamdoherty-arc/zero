# Weekly Covered Call Premium Collection Enhancement Plan

## Context

This enhancement transforms ADA's trade planner into a sophisticated weekly covered call premium collection system. The user focuses on weekly options that expire Fridays to collect premiums, with a need for:

- **Friday decision automation**: Know if options will be exercised and decide on actions
- **Weekend planning cycle**: Saturday account updates → Sunday planning → Monday execution  
- **Continuous learning**: Both user and ADA improve week-to-week through ML pipeline
- **ADA Employee integration**: Autonomous operation with weekly performance reports
- **Alert integration**: Leverage overkill scanner and stock alerts for opportunity discovery

**Problem being solved**: Current system has strong covered call scanning and learning infrastructure, but lacks Friday-centric workflows, weekend planning automation, and integrated weekly improvement cycles.

## Recommended Implementation Approach

### 1. Friday Expiration Workflow Engine

**Core Component**: `backend/services/friday_expiration_service.py`
- **3:45 PM ET Friday trigger**: Calculate assignment probability for all expiring positions
- **Decision logic**: Close/roll/expire recommendations with confidence scores based on:
  - Intrinsic value vs premium remaining
  - Implied volatility changes
  - Stock price momentum
  - User's profit targets (50% max profit rule)
- **Integration**: Extend existing `covered_call_scanner_service.py` (1,400+ lines of mature CC logic)
- **Database**: New `friday_expiration_decisions` table to track decisions and outcomes

### 2. Weekend Planning Service  

**Core Component**: `backend/services/weekend_planning_service.py`
- **Saturday 9 AM execution**: 
  - Process Friday outcomes from Robinhood sync
  - Run overkill bounce scanner for oversold recovery plays
  - Identify stocks with 100+ shares ready for covered calls
  - Calculate available buying power for new positions
- **Sunday 7 PM finalization**:
  - Integrate with existing `weekly_strategic_plan_service.py`
  - Generate Monday action plan with specific strikes/expirations
  - Risk assessment using existing portfolio Greeks tracking
- **Database**: New `weekend_cc_opportunities` table for planning persistence

### 3. Learning Pipeline Integration

**Enhancement**: Extend `backend/services/learning_feedback_service.py` 
- **Weekly pattern recognition**: 
  - Which stocks generate consistent CC premiums
  - Optimal delta ranges for user's risk tolerance
  - Market regime impact on CC success rates
  - Earnings proximity effects on volatility
- **Outcome tracking**: Link existing `learning_outcomes` table to CC-specific metrics
- **Calibration improvement**: Fix current 58.2% MAE in confidence scoring specifically for CC predictions
- **Performance attribution**: Weekly analysis of what worked vs what didn't

### 4. ADA Employee Weekly Automation

**Enhancement**: Extend `backend/services/ada_employee_service.py`
- **Friday preliminary report** (5:30 PM): Expiration outcomes, assignment status, next week preview
- **Sunday final report** (7:00 PM): Complete weekly performance analysis with specific improvements
- **Monday morning briefing**: Action items with prioritized CC opportunities
- **Autonomous operation**: Leverage existing autonomous decision engine for CC-specific workflows
- **Proactive messaging**: Integration with existing message system for risk alerts and opportunities

### 5. Frontend Weekly Dashboard

**New Component**: `frontend/src/components/planner/WeeklyCCDashboard.tsx`
- **Friday countdown**: Real-time expiration tracking with decision recommendations  
- **Weekend planner**: Visual planning interface for Monday setups
- **Learning insights**: Weekly performance trends and pattern recognition
- **Integration**: Embed in existing `TradePlannerHub.tsx` as new tab

## Critical Files to Modify

1. **`backend/services/covered_call_scanner_service.py`** - Enhance with Friday-specific logic and weekend scanning
2. **`backend/services/weekly_strategic_plan_service.py`** - Add CC-specific planning components  
3. **`backend/services/learning_feedback_service.py`** - CC pattern recognition and weekly learning cycles
4. **`backend/services/ada_employee_service.py`** - Weekly CC automation and reporting
5. **`backend/routers/trade_planner.py`** - New endpoints for Friday workflow and weekend planning
6. **`frontend/src/pages/TradePlannerHub.tsx`** - Integrate weekly CC dashboard

## Database Schema Changes

```sql
-- Track Friday expiration decisions and outcomes
CREATE TABLE friday_expiration_decisions (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    expiration_date DATE NOT NULL,
    strike_price DECIMAL(10,2) NOT NULL,
    decision VARCHAR(20) NOT NULL, -- 'CLOSE', 'ROLL', 'EXPIRE', 'TAKE_ASSIGNMENT'
    decision_time TIMESTAMPTZ NOT NULL,
    confidence_score DECIMAL(5,2),
    actual_outcome VARCHAR(20), -- Set Monday after settlement
    profit_loss DECIMAL(10,2),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Weekly performance tracking and lessons
CREATE TABLE weekly_cc_performance (
    id SERIAL PRIMARY KEY,
    week_start DATE NOT NULL,
    total_positions INTEGER NOT NULL,
    expired_positions INTEGER NOT NULL,
    rolled_positions INTEGER NOT NULL,
    assigned_positions INTEGER NOT NULL,
    total_premium_collected DECIMAL(12,2),
    win_rate DECIMAL(5,2),
    lessons_learned JSONB,
    improvements_identified JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Weekend opportunity scanning results
CREATE TABLE weekend_cc_opportunities (
    id SERIAL PRIMARY KEY,
    scan_date DATE NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    shares_owned INTEGER NOT NULL,
    recommended_strike DECIMAL(10,2),
    recommended_expiration DATE,
    premium_estimate DECIMAL(10,2),
    score DECIMAL(5,2),
    reasoning TEXT,
    executed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

## Implementation Schedule

**Week 1-2: Friday Expiration Framework**
- Create `friday_expiration_service.py` with decision logic
- Build database schema and basic API endpoints
- Test with paper trading integration

**Week 3-4: Weekend Planning System** 
- Enhance weekend scanning capabilities
- Build Sunday planning workflow
- Integrate with existing weekly strategic planning

**Week 5-6: Learning Pipeline Enhancement**
- CC-specific pattern recognition
- Weekly learning cycle automation
- Calibration improvement for CC predictions

**Week 7-8: ADA Employee Integration**
- Weekly reporting automation
- Autonomous operation enhancements  
- Proactive messaging for CC opportunities

**Week 9-10: Frontend and Testing**
- Weekly CC dashboard development
- End-to-end testing and refinement
- Performance optimization

## Success Metrics and Verification

### Quantitative Metrics
- **90%+ Friday decision accuracy**: Correct predictions on expire/assignment outcomes
- **85%+ weekend plan execution**: Monday trades executed as planned Sunday
- **15%+ CC win rate improvement**: Measured over 12-week period
- **60% reduction in manual monitoring**: Time saved through automation
- **<20% confidence calibration MAE**: Improved from current 58.2%

### Weekly Learning Indicators
- ADA employee generates actionable weekly reports with specific improvement recommendations
- Learning pipeline identifies profitable patterns and adjusts strategy accordingly  
- User receives clear feedback on "what could have been done differently"
- Week-over-week performance trending upward with measurable improvements

### Verification Process
1. **Friday 4 PM testing**: Verify expiration decision logic with paper trades
2. **Weekend planning verification**: Confirm Saturday scans find real opportunities
3. **Monday execution tracking**: Measure plan-to-actual execution rates
4. **Weekly learning validation**: Verify pattern recognition produces actionable insights
5. **ADA Employee report quality**: Ensure reports contain specific, actionable recommendations

## Risk Mitigation

- **Gradual rollout**: Start with paper trading, move to small position sizes
- **Human oversight**: All automated decisions include confidence scores and manual override
- **Learning validation**: Cross-reference ML insights with historical performance
- **Circuit breakers**: Automatic stops if win rates drop below thresholds
- **Data validation**: Robust error handling for market data and portfolio sync issues

This enhancement leverages ADA's existing strengths in covered call scanning, learning pipelines, and weekly planning while adding the missing Friday-centric workflows and weekend automation needed for systematic weekly premium collection.