# High-Priority Post-Drop Bounce Opportunities Implementation Plan

## Context

The user has identified their most successful trading pattern: buying stocks that have dropped significantly on earnings or news and then recover (examples: HIMS, UPS, TGT, SMCI, HOOD). They want ADA to surface these opportunities daily with higher priority in their trade planning workflow, create dedicated views/reports, and generate targeted alerts.

**Key Discovery**: ADA already has a sophisticated **Overkill Bounce Scanner** that detects exactly this pattern using a 7-factor scoring system. The infrastructure exists but these opportunities are not given priority over other strategies in the daily planning workflow.

## Current State Analysis

### Existing Systems (All Functional)

1. **Overkill Bounce Scanner** (`backend/services/overkill_bounce_scanner_service.py`)
   - 7-factor scoring: EMA Stack (25%), MACD Momentum (20%), Volume Confirmation (15%), Price Structure (15%), RSI Position (10%), Proximity to 52W Low (10%), Mean Reversion (5%)
   - Signal types: BUY (≥70), REVERSAL_SETUP (≥60), CORRECTION_WATCH (≥50)
   - Already integrated with alert system and daily planner

2. **Daily Planner Service** (`backend/services/daily_planner_service.py`)
   - Aggregates opportunities from multiple sources including overkill scanner
   - Uses multi-source boost scoring (+5 points per additional source)
   - Already includes bounce plays as `category: "bounce_play"` but treats them equally with other strategies

3. **Alert Hub System** (`frontend/src/components/alert-hub/DashboardTab.tsx`)
   - Comprehensive alert display with filtering and grouping
   - Already surfaces bounce plays but without special prominence

### The Gap

Bounce plays exist in the system but compete equally with CSP and other strategies rather than being prioritized. The user's most successful pattern needs elevated visibility and priority.

## Implementation Plan

### Phase 1: Elevate Bounce Play Priority (2-3 days)

**Objective**: Make bounce plays consistently appear in top daily recommendations

#### 1.1 Backend Priority Boost System

**File**: `backend/services/daily_planner_service.py`

```python
# In _fetch_overkill_opportunities() method (lines 600-658)
# Add priority boost for bounce plays

CATEGORY_PRIORITY_BOOSTS = {
    "bounce_play": 12,    # Significant boost for bounce plays
    "signal": 5,          # Moderate boost for XTrades signals  
    "csp": 0,             # Baseline (no boost)
    "covered_call": 0,    # Baseline
}

# In _merge_recommendations() method (lines 879-977)
# Apply category-based scoring after multi-source boost

for symbol, rec in by_symbol.items():
    category_boost = CATEGORY_PRIORITY_BOOSTS.get(rec.category, 0)
    if category_boost > 0:
        original_score = rec.score
        rec.score = min(100, rec.score + category_boost)
        rec.reasoning += f" | Priority boost: +{category_boost}"
```

#### 1.2 Enhanced Bounce Play Alerts

**File**: `backend/services/overkill_bounce_scanner_service.py`

```python
# Lower threshold for bounce play alerts from 70 to 60
# Add special bounce play branding and priority flags

if r.composite_score >= 60:  # Lowered threshold
    alert_title = f"🎯 BOUNCE PLAY: {r.symbol} ({r.grade})"
    alert_message = (f"Post-drop bounce opportunity scored {r.composite_score:.0f}/100. "
                    f"{r.signal_type} signal detected with {r.recommendation}.")
    
    # Mark as high priority bounce play alert
    await create_priority_alert(
        symbol=r.symbol,
        alert_type=f"bounce_play_{r.signal_type.lower()}",
        title=alert_title,
        message=alert_message,
        priority_level="high",
        category="bounce_play"
    )
```

**Expected Outcome**: Bounce plays consistently rank in top 5 daily recommendations and generate more frequent alerts.

### Phase 2: Dedicated Bounce Play Dashboard (3-4 days)

**Objective**: Create prominent dedicated views for bounce opportunities

#### 2.1 Main Dashboard Widget

**New File**: `frontend/src/components/dashboard/BouncePlayWidget.tsx`

```tsx
export function BouncePlayWidget() {
    const { data: bounceOpps } = useQuery({
        queryKey: ['bounce-opportunities'],
        queryFn: async () => {
            const { data } = await axiosInstance.get('/api/scanner/overkill/signals/BUY');
            return data.results.slice(0, 8);
        },
        staleTime: 300000, // 5 minutes
    });

    return (
        <div className="bg-slate-800 rounded-xl border border-amber-500/20 p-4">
            <div className="flex items-center gap-2 mb-4">
                <div className="p-2 rounded-lg bg-amber-500/20">
                    <TrendingUp className="w-5 h-5 text-amber-400" />
                </div>
                <div>
                    <h3 className="font-semibold text-amber-300">🎯 Today's Bounce Plays</h3>
                    <p className="text-xs text-slate-400">Post-drop recovery opportunities</p>
                </div>
            </div>
            <div className="space-y-2">
                {bounceOpps?.map((opp) => (
                    <BouncePlayCard key={opp.symbol} opportunity={opp} />
                ))}
            </div>
        </div>
    );
}
```

#### 2.2 Daily Bounce Play Report Endpoint

**File**: `backend/routers/overkill_bounce_scanner.py`

```python
@router.get("/daily-report")
async def get_daily_bounce_report():
    """Generate comprehensive daily bounce play report."""
    
    opportunities = await service.get_signals_by_type("BUY", limit=20)
    reversal_setups = await service.get_signals_by_type("REVERSAL_SETUP", limit=15)
    
    # Analyze sector distribution
    sector_breakdown = await _analyze_bounce_sectors(opportunities)
    
    # Track new opportunities (last 24h)
    recent_opps = await db.fetch("""
        SELECT symbol, composite_score, signal_type, scanned_at
        FROM overkill_scan_results 
        WHERE signal_type IN ('BUY', 'REVERSAL_SETUP')
          AND scanned_at > NOW() - INTERVAL '24 hours'
          AND composite_score >= 65
        ORDER BY scanned_at DESC
    """)
    
    return {
        "date": date.today().isoformat(),
        "summary": {
            "total_opportunities": len(opportunities) + len(reversal_setups),
            "high_conviction": len([o for o in opportunities if o.get("composite_score", 0) >= 80]),
            "new_today": len(recent_opps),
            "sectors_represented": len(set(sector_breakdown.keys()))
        },
        "top_opportunities": opportunities[:10],
        "reversal_setups": reversal_setups[:8],
        "sector_breakdown": sector_breakdown,
        "recent_developments": recent_opps,
        "market_context": await _get_bounce_market_context()
    }
```

#### 2.3 Dashboard Integration

**File**: `frontend/src/pages/Dashboard.tsx`

Add BouncePlayWidget to main dashboard grid, positioned prominently above existing widgets.

**Expected Outcome**: Users see dedicated bounce play section on main dashboard with clear visual distinction and daily reporting.

### Phase 3: Smart Bounce Play Intelligence (4-5 days)

**Objective**: Add context and automation for bounce play identification

#### 3.1 Enhanced Trade Planner Integration

**File**: `backend/services/daily_planner_service.py`

```python
# Enhanced bounce play recommendations with context
for rec in bounce_play_recs:
    if rec.category == "bounce_play":
        # Add bounce-specific context
        rec.reasoning += " | 🎯 POST-DROP BOUNCE OPPORTUNITY"
        
        # Add entry timing guidance
        if rec.score >= 80:
            rec.warnings.insert(0, "⚡ HIGH CONVICTION: Monitor for pullback entry")
        elif rec.score >= 65:
            rec.warnings.insert(0, "📊 SOLID SETUP: Watch for volume confirmation")
        
        # Boost high-quality bounce plays even further
        if rec.score >= 75:
            rec.score = min(100, rec.score + 5)  # Additional boost for quality
```

#### 3.2 Bounce Play Performance Tracking

**New File**: `backend/services/bounce_play_analytics_service.py`

Track outcomes of bounce plays to optimize strategy:
- Success rates by signal type (BUY vs REVERSAL_SETUP)
- Average holding periods and returns
- Sector performance patterns
- Market regime effectiveness

#### 3.3 Advanced Alert Conditions

**File**: `backend/services/alert_rule_engine.py`

Add smart rule template for bounce plays:
```python
BOUNCE_PLAY_RULE_TEMPLATE = {
    "name": "High-Conviction Bounce Play",
    "conditions": {
        "operator": "AND",
        "conditions": [
            {"type": "overkill_score_above", "value": 70},
            {"type": "volume_spike", "value": 1.5},
            {"type": "rsi_oversold_recovery", "value": 35},
            {"type": "price_near_support", "value": 3}  # Within 3% of support
        ]
    },
    "actions": ["notify", "add_to_planner", "paper_trade"],
    "cooldown_minutes": 240,
    "max_triggers_per_day": 2
}
```

**Expected Outcome**: Intelligent bounce play detection with contextual guidance and performance optimization.

## Critical Files to Modify

1. `backend/services/daily_planner_service.py` (lines 600-658, 879-977) - Priority boost logic
2. `backend/services/overkill_bounce_scanner_service.py` (alert generation) - Enhanced alerts  
3. `frontend/src/pages/Dashboard.tsx` - Dashboard widget integration
4. `backend/routers/overkill_bounce_scanner.py` - Daily report endpoint
5. `frontend/src/components/dashboard/BouncePlayWidget.tsx` - New widget component

## Database Schema Changes

```sql
-- Add priority level to alerts table
ALTER TABLE real_time_alerts ADD COLUMN priority_level VARCHAR(20) DEFAULT 'medium';
CREATE INDEX idx_alerts_priority ON real_time_alerts(priority_level, created_at DESC) WHERE is_active = TRUE;

-- Track bounce play outcomes for learning
CREATE TABLE bounce_play_outcomes (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    entry_date DATE NOT NULL,
    entry_price DECIMAL(10,2),
    outcome VARCHAR(20), -- 'success', 'failure', 'pending'
    max_gain_pct DECIMAL(10,4),
    final_pnl_pct DECIMAL(10,4),
    signal_type VARCHAR(20), -- 'BUY', 'REVERSAL_SETUP'
    composite_score FLOAT,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_bounce_outcomes_symbol_date ON bounce_play_outcomes(symbol, entry_date DESC);
```

## Verification Plan

### End-to-End Testing

1. **Bounce Play Detection**: Verify overkill scanner identifies post-drop opportunities with scores ≥60
2. **Priority Ranking**: Confirm bounce plays appear in top 5 daily recommendations 80%+ of trading days
3. **Alert Generation**: Test that bounce opportunities generate high-priority alerts with clear branding
4. **Dashboard Integration**: Verify BouncePlayWidget displays on main dashboard with real data
5. **Daily Reports**: Confirm `/api/scanner/overkill/daily-report` returns comprehensive bounce play analysis

### Performance Validation

- Monitor daily recommendation API response times (should remain <2s)
- Verify overkill scanner cache performance (5-minute TTL)  
- Test alert generation load (should handle 50+ symbols without issues)
- Validate database query performance with new indexes

### User Experience Testing

1. Load dashboard and verify bounce play widget prominence
2. Review daily recommendations to confirm bounce plays rank highly
3. Test alert filtering and grouping with bounce play category
4. Verify one-click trade planning from bounce play alerts

## Success Metrics

**Phase 1 Success**:
- Bounce plays rank in top 5 daily recommendations on 80%+ of trading days
- 40%+ increase in bounce play alert generation 
- Clear visual distinction for bounce opportunities in UI

**Phase 2 Success**:
- Dedicated bounce play dashboard shows 8-10 opportunities daily
- Daily bounce report provides comprehensive market context
- Integration with existing trade planning workflow functions smoothly

**Phase 3 Success**:
- Smart bounce play detection with 85%+ accuracy
- Performance tracking shows measurable win rate data
- User engagement with bounce plays increases 60%+

## Risk Mitigation

1. **Performance**: All changes leverage existing caching and database indexes
2. **Data Quality**: Overkill scanner already battle-tested with 7-factor validation
3. **User Experience**: Incremental additions to existing UI patterns
4. **Rollback**: Each phase can be independently disabled via feature flags

This plan leverages ADA's existing sophisticated bounce detection infrastructure while making these high-probability opportunities much more prominent and actionable for the user's proven successful trading strategy.