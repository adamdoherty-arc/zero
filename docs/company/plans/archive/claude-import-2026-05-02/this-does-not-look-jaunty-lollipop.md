# Covered Calls Scanning: Timeout & Update Fix Plan

## Context

The covered calls scanning system is experiencing two critical issues that prevent users from getting current covered call data:

1. **Timeout Issue**: Scans fail with "timeout of 180000ms exceeded" error due to performance bottlenecks
2. **Update Issue**: Covered calls data becomes stale and doesn't refresh properly throughout trading hours

### Root Causes Identified

**Timeout Causes:**
- API semaphore limiting to only 3 concurrent Tradier calls creates bottleneck
- Missing database indexes for CALL options (only PUT indexes exist) 
- N+1 database queries for option chains instead of batch fetching
- 5-second delays between 200-symbol batches in background scanner

**Update Causes:**
- 10-minute backend cache TTL serves stale premium data
- 5-minute frontend staleTime prevents real-time refreshing
- Only 3 scans daily (10 AM, 1 PM, 4:30 PM ET) leaving 8+ hour gaps
- No cache invalidation after scans complete
- No event-driven refresh mechanisms

## Implementation Plan

### Phase 1: Database Performance Optimization

#### Add Missing CALL Option Indexes
**File**: Create new migration `backend/infrastructure/migrations/add_covered_call_indexes.sql`

```sql
-- Composite index for covered call quality filtering
CREATE INDEX idx_premium_call_quality_composite ON premium_opportunities(
    option_type,
    dte,
    premium_pct,
    annualized_return DESC NULLS LAST,
    delta DESC NULLS LAST,
    last_updated DESC
) WHERE option_type = 'CALL' AND last_updated >= CURRENT_DATE - INTERVAL '7 days';

-- Deduplication index for covered calls
CREATE INDEX idx_premium_call_dedup ON premium_opportunities(
    symbol,
    strike,
    expiration,
    last_updated DESC
) WHERE option_type = 'CALL';

-- High-quality covered call lookup index
CREATE INDEX idx_premium_call_high_quality ON premium_opportunities(
    annualized_return DESC,
    premium_pct DESC,
    delta DESC
) WHERE option_type = 'CALL'
  AND delta BETWEEN 0.15 AND 0.45
  AND annualized_return >= 15
  AND last_updated >= CURRENT_DATE - INTERVAL '7 days';
```

#### Optimize Batch Database Queries
**File**: `backend/services/covered_call_scanner_service.py`

Replace N+1 option chain queries with batch fetching:
- Implement `_batch_option_chains()` method to fetch multiple symbols/expirations at once
- Use `WHERE symbol = ANY($1::text[])` pattern for batch position lookup
- Add composite query for earnings/IV rank/VRP data in single call

### Phase 2: API Performance Optimization

#### Increase API Concurrency
**File**: `backend/services/covered_call_scanner_service.py`

```python
# Increase concurrent API calls from 3 to 8
_API_SEMAPHORE_LIMIT = 8  # Was 3
BATCH_SIZE = 25           # Process 25 symbols per batch
BATCH_DELAY = 2.0         # Reduce from 5s to 2s between batches
```

#### Smart Batch Processing
**File**: `backend/services/covered_call_scanner_service.py`

- Implement prioritized symbol scanning (largest positions first)
- Add progressive loading to scan high-priority symbols first
- Use smart batching to process similar symbols together

### Phase 3: Caching Strategy Overhaul

#### Reduce Cache TTLs for Real-Time Data
**File**: `backend/infrastructure/cache.py`

```python
class CacheTTL(int, Enum):
    COVERED_CALL_SCAN = 120     # 2 minutes (was 300)
    PREMIUM_DATA = 180          # 3 minutes (was 600)
    OPTION_CHAIN = 90           # 1.5 minutes (new)

# Update scanner cache namespace
NAMESPACE_TTL_DEFAULTS = {
    CacheNamespace.SCANNER: CacheTTL.COVERED_CALL_SCAN.value,
}
```

#### Implement Event-Driven Cache Invalidation
**File**: `backend/services/covered_call_scanner_service.py`

- Add `_invalidate_related_caches()` method called after scan completion
- Clear premium data cache when new opportunities are persisted
- Implement cache invalidation hooks for related data

### Phase 4: Background Scan Scheduling

#### Increase Scan Frequency to Every 2 Hours
**File**: `backend/services/premium_scanner_scheduler.py`

```python
# New schedule: every 2 hours during market hours
COVERED_CALL_SCAN_SCHEDULE = [
    "09:45",  # Market open + 15 min
    "11:45",  # Mid-morning  
    "13:45",  # After lunch
    "15:45",  # Late afternoon
    "17:15",  # After market close
]
```

#### Progressive Symbol Scanning
**File**: `backend/services/covered_call_scanner_service.py`

- Scan largest positions first to reduce perceived latency
- Implement early termination if scan takes too long
- Add position value-based priority sorting

### Phase 5: Frontend Real-Time Updates

#### Reduce Frontend Stale Time
**File**: `frontend/src/hooks/useMarginCC.ts`

```typescript
export const useCoveredCallOpportunities = () => {
    return useQuery({
        queryKey: ['covered-calls'],
        queryFn: fetchCoveredCalls,
        staleTime: 2 * 60 * 1000,      // 2 minutes (was 5 minutes)
        refetchInterval: 3 * 60 * 1000, // Auto-refresh every 3 minutes
        placeholderData: keepPreviousData, // Show old data while fetching
    });
};
```

#### Event-Driven Frontend Updates
**File**: `frontend/src/components/scanner/CoveredCallsTab.tsx`

- Add WebSocket listener for scan completion events
- Implement automatic table refresh when scan completes
- Add progressive loading indicators

### Phase 6: Performance Monitoring

#### Add Scan Performance Tracking
**File**: `backend/services/covered_call_scanner_service.py`

- Monitor scan duration and alert when > 150 seconds
- Track API call counts and rate limit usage
- Log performance metrics for each scan phase

#### Frontend Performance Indicators
**File**: `frontend/src/components/scanner/CoveredCallsTab.tsx`

- Add data freshness indicators ("Updated 2 minutes ago")
- Show scan progress during long operations
- Display performance warnings if data is stale

## Critical Files to Modify

### Backend Files
1. **`backend/services/covered_call_scanner_service.py`** - Core scanning logic optimization
2. **`backend/infrastructure/cache.py`** - TTL adjustments and cache invalidation
3. **`backend/services/premium_scanner_scheduler.py`** - Scan frequency and scheduling
4. **`backend/routers/scanner.py`** - API endpoint timeout handling
5. **`backend/infrastructure/migrations/`** - New database indexes migration

### Frontend Files
1. **`frontend/src/components/scanner/CoveredCallsTab.tsx`** - UI refresh and progress
2. **`frontend/src/hooks/useMarginCC.ts`** - Query configuration and cache management
3. **`frontend/src/lib/axios.ts`** - Timeout configuration verification

## Performance Targets

### Before Optimization
- Scan timeout: 180+ seconds (frequent failures)
- Data staleness: Up to 15 minutes
- Scan frequency: 3x daily (10 AM, 1 PM, 4:30 PM)
- API bottleneck: 3 concurrent calls

### After Optimization  
- Scan completion: <150 seconds (95% success rate)
- Data staleness: <3 minutes average
- Scan frequency: Every 2 hours during market hours (5x daily)
- API throughput: 8 concurrent calls + smart batching

## Verification Steps

### Database Performance
- Verify all covered call queries use new indexes via `EXPLAIN ANALYZE`
- Confirm query execution time <500ms for typical position sets
- Test batch queries handle 100+ symbols efficiently

### API Performance
- Monitor Tradier API usage stays under 120 req/min limit
- Verify 8 concurrent calls don't hit rate limits
- Test scan completion under 150 seconds for 50+ positions

### Cache Effectiveness
- Verify cache hit rates >80% for premium data
- Confirm cache invalidation triggers after scans
- Test frontend receives fresh data within 3 minutes

### End-to-End Functionality
- Test manual "Scan Positions" button completes without timeout
- Verify covered calls data auto-refreshes every 2 hours
- Confirm UI shows current premium values and doesn't serve stale data
- Test WebSocket notifications trigger UI refresh after scans

### Integration Testing
- Test position scanning for IREN, IREX, NEBX, OKLL, ONDG symbols
- Verify covered call opportunities display current premiums
- Confirm "1 Covered Call Available to Write" calculations are accurate
- Test scan progress indicators during long operations

## Risk Mitigation

### Database Migration Safety
- Create indexes `CONCURRENTLY` to avoid locking
- Test index performance on production-size data
- Have rollback plan for index removal if issues arise

### API Rate Limiting
- Monitor Tradier API usage carefully during testing
- Implement fallback to lower concurrency if rate limits hit
- Add circuit breaker for API failures

### Cache Consistency
- Ensure cache invalidation doesn't create race conditions
- Test cache behavior under high concurrent load
- Verify stale data doesn't persist after invalidation

This comprehensive plan addresses both timeout and update issues simultaneously while maintaining data accuracy and system stability. The phased approach allows for testing and validation at each step.