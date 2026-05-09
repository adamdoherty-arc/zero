# PostgreSQL Database Growth Crisis - Cleanup and Retention Plan

## Context

The ADA Trading Platform's local PostgreSQL database has consumed all available hard drive space due to unchecked data growth. Investigation revealed that **comprehensive database cleanup infrastructure exists but is not actively running**. The platform has:

- A production-ready database cleanup service (`database_cleanup_service.py`) with 50+ table retention policies
- Three critical cleanup functions defined but **NOT scheduled** to run automatically
- High-volume data sources accumulating without cleanup: premium scanning (5x daily, 11k symbols), metrics collection (hourly), Discord signals, error logging
- Tables using ON CONFLICT upsert patterns creating dead tuples without regular VACUUM operations

**Root Cause**: Database cleanup service exists but cleanup jobs are not registered in the main scheduler (`scheduled_tasks.py`).

**Immediate Risk**: Database will continue growing until complete disk exhaustion occurs.

**Good News**: The cleanup infrastructure is comprehensive and can provide immediate relief.

## Implementation Approach

### Phase 1: Immediate Space Recovery (1-2 hours)

**Execute manual cleanup operations to recover 2-5GB immediately:**

1. **Dry Run Assessment**
   ```bash
   curl -X POST "http://localhost:8006/api/system/db-cleanup" \
     -H "Content-Type: application/json" \
     -d '{"dry_run": true, "include_vacuum": true, "include_sizes": true}'
   ```

2. **Aggressive Cleanup for Space Recovery**
   ```bash
   curl -X POST "http://localhost:8006/api/system/db-cleanup" \
     -H "Content-Type: application/json" \
     -d '{
       "dry_run": false,
       "include_vacuum": true,
       "cache_days": 3,
       "metrics_days": 14,
       "error_logs_days": 14
     }'
   ```

3. **VACUUM Operations for Dead Tuple Recovery**
   - Automatically included in cleanup operations
   - Targets high-volume tables: `premium_opportunities`, `endpoint_metrics`, `error_logs`, `discord_trading_signals`

### Phase 2: Automated Cleanup Activation (2 hours)

**Fix the root cause by scheduling the existing cleanup functions:**

1. **Register Missing Cleanup Jobs in Scheduler**
   - File: `backend/services/scheduled_tasks.py`
   - Add three functions to `start_scheduler()`: `scheduled_weekly_cleanup`, `scheduled_weekend_vacuum`, `scheduled_table_growth_snapshot`
   - Import functions from `database_cleanup_service.py`

2. **Schedule Configuration**
   ```python
   # Weekly cleanup - Sunday 2:00 AM ET (low activity)
   _scheduler.add_job(
       _guarded(scheduled_weekly_cleanup),
       'cron', day_of_week='sun', hour=2, minute=0,
       timezone=ZoneInfo('America/New_York'),
       id='database_weekly_cleanup', max_instances=1
   )
   
   # Weekend VACUUM - Saturday 1:00 AM ET  
   _scheduler.add_job(
       _guarded(scheduled_weekend_vacuum),
       'cron', day_of_week='sat', hour=1, minute=0,
       timezone=ZoneInfo('America/New_York'),
       id='database_weekend_vacuum', max_instances=1
   )
   
   # Daily growth tracking - 11:45 PM ET
   _scheduler.add_job(
       _guarded(scheduled_table_growth_snapshot),
       'cron', hour=23, minute=45,
       timezone=ZoneInfo('America/New_York'),
       id='table_growth_snapshot', max_instances=1
   )
   ```

3. **Backend Restart Required**
   ```bash
   docker restart ada-backend
   ```

### Phase 3: Configuration and Monitoring (1 hour)

**Make retention periods configurable and add monitoring:**

1. **Environment Configuration**
   - Add retention period environment variables to `backend/config.py`
   - Support override of default retention periods (7-180 days) via `.env`

2. **Health Check Integration**
   - Add database cleanup component to health monitoring system
   - Alert when cleanup hasn't run in >7 days

3. **Failure Alerting**
   - Discord notifications for cleanup job failures
   - Performance alerts for cleanup operations >5 minutes

### Phase 4: Optimization (Future Sprint)

**Architectural improvements for long-term performance:**

1. **High-Volume Table Optimization**
   - Implement partitioning for `premium_opportunities`, `endpoint_metrics`, `error_logs`
   - Move cache tables from PostgreSQL to Redis
   - Expand TimescaleDB usage for time-series data

2. **Dead Tuple Management**
   - Tune autovacuum settings for high-update tables
   - Consider alternatives to ON CONFLICT patterns for metrics collection

## Critical Files to Modify

1. **`backend/services/scheduled_tasks.py`**
   - Add imports for cleanup functions
   - Register three cleanup jobs in `start_scheduler()`

2. **`backend/services/database_cleanup_service.py`**
   - Already complete with comprehensive retention policies
   - May need alerting integration for failures

3. **`backend/config.py`**
   - Add configurable retention period environment variables
   - Enable runtime configuration of cleanup behavior

## Verification Steps

### Immediate Cleanup Verification
```bash
# Check space recovery
curl "http://localhost:8006/api/system/health" | jq '.services.database'

# Verify table sizes reduced
curl "http://localhost:8006/api/system/database-sizes"

# Check dead tuple ratios improved
curl -X POST "http://localhost:8006/api/system/db-cleanup" \
  -d '{"dry_run": true, "include_bloat": true}'
```

### Automation Verification
```bash
# Check jobs are scheduled
curl "http://localhost:8006/api/system/scheduled-jobs" | jq '.[] | select(.id | contains("cleanup"))'

# Monitor job execution logs
docker logs ada-backend --tail 100 | grep -i cleanup
```

### Long-term Monitoring
- Weekly review of database size trends
- Monitor cleanup job success rates
- Track space recovery amounts
- Alert on >1GB table growth rates

## Expected Outcomes

### Immediate Relief (Phase 1)
- **2-5GB disk space recovery** from cleanup operations
- **Dead tuple ratio reduction** from VACUUM operations
- **Query performance improvement** for cleanup tables

### Long-term Prevention (Phase 2-3)
- **Automated weekly cleanup** preventing future growth crises
- **Configurable retention** allowing fine-tuning per environment
- **Proactive monitoring** with alerting for issues

### Performance Improvements (Phase 4)
- **40-60% reduction in table bloat** through proper vacuum scheduling
- **Query performance improvements** from optimized indexing and partitioning
- **Storage efficiency gains** through compression and archival strategies

## Risk Assessment

**Low Risk Operations** (Execute immediately):
- Manual cleanup with dry-run verification
- VACUUM ANALYZE operations  
- Table size analysis

**Medium Risk Operations** (Test first):
- Scheduler job registration (requires backend restart)
- Aggressive retention period cleanup

**Safety Guarantees**:
- ✅ Cleanup never drops tables or truncates
- ✅ Only deletes rows older than retention periods
- ✅ Parameterized queries prevent SQL injection
- ✅ Comprehensive logging of all operations
- ✅ Dry-run mode for testing

**Recovery Plan**:
- All cleanup operations are logged and reversible
- Table size snapshots track changes
- Health monitoring detects failures immediately
- Discord alerting ensures operational awareness

## Success Metrics

- **Immediate**: 2-5GB space recovery within 2 hours
- **Short-term**: 99% cleanup job success rate
- **Long-term**: <5% monthly database growth rate
- **Performance**: <5 minute cleanup operations, <15% table bloat ratio