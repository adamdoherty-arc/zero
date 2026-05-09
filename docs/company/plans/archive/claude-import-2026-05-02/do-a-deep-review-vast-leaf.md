# Discord Notifications Deep Review & Enhancement Plan

## Context

The Discord notifications system is currently broken and providing repetitive, unhelpful messages. The user is seeing multiple "Daily Market Briefing" messages with zero values (0 positions, 0 alerts, $0.00 P&L) sent at different times throughout the day. Additionally, the platform has recently built an enhanced daily reports system that should be integrated with Discord to provide more valuable insights.

**Root Problems Identified:**
1. **Morning briefings (8 AM)** show repetitive zero values due to wrong data source queries
2. **Enhanced daily reports (5:30 PM)** exist but may not be properly showcased in Discord 
3. **Multiple scheduling issues** causing duplicate messages
4. **Poor content quality** with hardcoded defaults instead of intelligent fallbacks

## Current State Analysis

**Broken Morning Briefings:**
- Scheduler queries `portfolio_summary` table (line 178-188 of `daily_briefing_scheduler.py`)  
- Should query `cached_portfolio_summary` table instead
- Falls back to hardcoded defaults (VIX=15.0, regime="ranging") when data missing
- No distributed locking causing potential duplicate sends
- "briefing" channel excluded from Signal Gateway deduplication

**Enhanced Daily Reports Status:**
- ✅ Infrastructure exists (`enhanced_daily_report_scheduler.py`, database schema, API endpoints)
- ✅ Scheduled for weekdays 5:30 PM ET with comprehensive data collection
- ❓ Discord integration confirmed but content quality unknown
- ❓ May not be showcasing the rich enhanced data (scanner results, AI narrative, learning insights)

## Implementation Plan

### Phase 1: Fix Critical Data Source Issues

**1.1 Fix Portfolio Data Query (HIGH PRIORITY)**
- File: `backend/services/daily_briefing_scheduler.py` (lines 177-196)
- Change query from `portfolio_summary` to `cached_portfolio_summary` 
- Update column names to match actual schema: `total_equity`, `daily_change`, `daily_change_pct`
- Add fallback to previous day's cached data if current data is stale

**1.2 Fix Market Data Defaults (HIGH PRIORITY)**  
- File: `backend/services/daily_briefing_scheduler.py` (lines 152-168)
- Replace hardcoded defaults with intelligent fallback logic
- Add staleness checks for `market_regime_history` table
- Show helpful messages like "Market data syncing..." instead of hardcoded values

**1.3 Add Smart Zero-Value Handling (MEDIUM PRIORITY)**
- File: `backend/services/discord/embeds/briefing_embed.py`
- Add validation for zero/null values before building embeds
- Replace "$0.00" displays with contextual messages like "Portfolio data loading..."
- Include data freshness indicators in embed footers

### Phase 2: Implement Distributed Coordination

**2.1 Add Redis-Based Distributed Locking**
- Create `NotificationCoordinator` service using existing Redis infrastructure
- Implement distributed locks with 6-hour TTL for briefing generation
- Use lock key pattern: `ada:briefing:lock:{date}`
- Add automatic lock renewal and graceful failover

**2.2 Fix Signal Gateway Deduplication**
- File: `backend/services/discord/event_consumer.py` (line 71)
- Confirm "briefing" events route to Discord but verify deduplication
- Add briefing events to Signal Gateway deduplication system if missing
- Implement 24-hour TTL for briefing event deduplication

**2.3 Persistent State Management**
- Replace in-memory `_last_briefing` state with Redis persistence
- Add database tracking in `notification_execution_log` table
- Implement state recovery mechanism for scheduler restarts

### Phase 3: Enhanced Daily Reports Discord Integration

**3.1 Verify Enhanced Reports Generation**
- Run verification script: `scripts/verify_enhanced_daily_reports.py`
- Check database for recent enhanced reports with non-null JSONB fields
- Monitor 5:30 PM ET scheduler execution and success rates
- Test manual generation via API: `POST /api/briefings/enhanced/{date}/regenerate`

**3.2 Create Rich Discord Embeds for Enhanced Reports**
- File: `backend/services/discord/embeds/briefing_embed.py` 
- Add new functions:
  - `build_enhanced_summary_embed()` - High-level overview with key metrics
  - `build_scanner_highlights_embed()` - Top scanner results (overkill, contrarian, CSP, etc.)
  - `build_ai_insights_embed()` - AI narrative and learning insights
- Implement smart content selection to prioritize meaningful, non-zero data
- Add color-coded embeds based on market sentiment/regime

**3.3 Implement Content Rotation Strategy**
- Create time-sensitive content focus:
  - **Morning (8 AM)**: Portfolio status, pre-market opportunities, alerts
  - **Evening (5:30 PM)**: Scanner highlights, AI narrative, post-market analysis
- Add daily content rotation to avoid repetition
- Implement conditional display logic to hide empty sections

### Phase 4: Monitoring and Health Checks

**4.1 Add Notification Pipeline Monitoring**
- Implement health checks for data source freshness (`cached_portfolio_summary.synced_at`)
- Add alerting for repeated scheduler failures or stale data
- Monitor Discord delivery success rates and engagement

**4.2 Configuration Management**
- Move hardcoded values to environment configuration:
  - Briefing times (currently 8:00 AM, 5:30 PM hardcoded)
  - Rate limits and thresholds
  - Data staleness tolerances
- Add admin API for runtime configuration updates

**4.3 Quality Assurance**
- Add content quality validation before Discord sends
- Implement fallback messaging when enhanced data is unavailable
- Add user feedback mechanisms via Discord reactions

## Verification Steps

### After Phase 1 (Data Fixes):
1. Run `docker restart ada-backend` and monitor startup logs
2. Check morning briefing at 8 AM shows real portfolio values, not zeros
3. Verify market regime shows current data, not hardcoded "ranging" 
4. Confirm no duplicate briefing messages in Discord

### After Phase 2 (Coordination):
1. Test scheduler restart behavior - verify no duplicate sends
2. Monitor Redis for distributed lock creation and cleanup
3. Confirm Signal Gateway properly deduplicates briefing events

### After Phase 3 (Enhanced Reports):
1. Verify 5:30 PM enhanced reports generate successfully
2. Check Discord embeds show rich content (scanner results, AI narrative)
3. Confirm content varies day-to-day and doesn't show repetitive zeros
4. Test manual report generation and Discord delivery

### After Phase 4 (Monitoring):
1. Verify health check endpoints respond correctly
2. Test configuration updates via admin API
3. Monitor notification pipeline metrics and alerting

## Success Criteria

**Immediate (Post-Phase 1):**
- Discord briefings show real portfolio data instead of zeros
- Market regime reflects current conditions, not hardcoded defaults  
- No more repetitive identical messages throughout the day

**Medium-term (Post-Phase 3):**
- Enhanced daily reports visible in Discord with rich, varied content
- Scanner highlights and AI insights prominently displayed
- Clear differentiation between morning briefings and evening enhanced reports

**Long-term (Post-Phase 4):**
- Reliable, coordinated notification delivery across container restarts
- Comprehensive monitoring and alerting for notification health
- Configurable timing and content without code changes

## Critical Files to Modify

### High Priority (Phase 1):
- `backend/services/daily_briefing_scheduler.py` - Fix data queries and defaults
- `backend/services/discord/embeds/briefing_embed.py` - Add smart zero handling

### Medium Priority (Phase 2):
- `backend/services/discord/event_consumer.py` - Verify/fix deduplication
- `backend/infrastructure/` - Add NotificationCoordinator service

### Enhancement (Phase 3):
- `backend/services/enhanced_daily_report_scheduler.py` - Verify operation
- `backend/services/discord/embeds/briefing_embed.py` - Add enhanced embed builders

### Infrastructure (Phase 4):
- `backend/config/` - Add notification configuration management
- `backend/routers/` - Add admin APIs for monitoring and configuration

## Risk Mitigation

- **Backwards Compatibility**: Maintain existing API interfaces during migration
- **Gradual Rollout**: Implement fixes incrementally with feature flags
- **Data Safety**: Use database transactions for all state operations
- **Monitoring**: Add comprehensive logging for debugging and troubleshooting
- **Rollback Plan**: Ability to revert to previous scheduler behavior if needed

This plan addresses both the immediate broken Discord notifications and ensures the enhanced daily reports system provides maximum value through improved Discord integration.