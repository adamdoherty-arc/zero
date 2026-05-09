# Weekly Planner Fix Plan - Comprehensive Solution

## Context

The ADA weekly planner system has multiple interconnected issues causing incorrect model attribution, stale timestamps, and parsing failures. After deep investigation, the root causes are:

1. **LLM Provider Misconfiguration**: Trade advisor uses wrong task type (FINANCIAL_ANALYSIS) that only routes to local Ollama instead of cloud models like MiniMax M2.7
2. **Model Attribution Failures**: Both services hardcode model names instead of capturing actual model used
3. **Timestamp Inconsistencies**: Weekly plan only shows `created_at` (original), not refresh time; trade advisor shows `generated_at` (refresh-aware)
4. **Caching Strategy Mismatch**: Trade advisor caches aggressively, weekly plan bypasses cache entirely
5. **Documentation Lag**: References still mention deprecated "Kimi K2.5" when system uses MiniMax M2.7

This causes users to see "40d ago" timestamps (accurate but stale data) and "Kimi 2.5" labels (incorrect model references).

## Implementation Plan

### Phase 1: LLM Router & Model Attribution Fixes

**Critical Files:**
- `backend/services/trade_advisor_service.py` (lines 1695-1709)
- `backend/services/weekly_strategic_plan_service.py` (lines 1855-1868)

**Changes:**

1. **Trade Advisor Service** (`trade_advisor_service.py`):
   ```python
   # Line 1700: Change task type
   task_type=TaskType.PLANNING,  # Was: TaskType.FINANCIAL_ANALYSIS
   
   # Lines 1697-1709: Replace generate_text() with generate_text_with_usage()
   ai_result = await get_router().generate_text_with_usage(
       prompt=prompt,
       system=system_prompt,
       task_type=TaskType.PLANNING,
       temperature=0.3,
       max_tokens=max_tokens,
       feature="trade_advisor"
   )
   content = ai_result["content"]
   # Use ai_result["model"] instead of hardcoded "ollama-router"
   ```

2. **Weekly Strategic Plan Service** (`weekly_strategic_plan_service.py`):
   ```python
   # Lines 1855-1868: Replace generate_text() with generate_text_with_usage()
   ai_result = await get_router().generate_text_with_usage(
       prompt=prompt,
       system=system_prompt,
       task_type=TaskType.PLANNING,
       temperature=0.3,
       max_tokens=6144,
       feature="weekly_plan"
   )
   return {
       "content": ai_result["content"],
       "model": ai_result["model"],  # Was: hardcoded "ollama-planning"
       "input_tokens": ai_result["input_tokens"],
       "output_tokens": ai_result["output_tokens"], 
       "cost_usd": ai_result["cost_usd"]
   }
   ```

### Phase 2: Database Schema Enhancement

**Database Migration** (new file: `backend/alembic/versions/YYYYMMDD_add_refresh_timestamps.py`):
```sql
ALTER TABLE weekly_strategic_plans 
ADD COLUMN last_refreshed_at TIMESTAMPTZ DEFAULT NOW();

-- Initialize existing records with created_at value
UPDATE weekly_strategic_plans 
SET last_refreshed_at = created_at 
WHERE last_refreshed_at IS NULL;

-- Add index for efficient queries
CREATE INDEX idx_weekly_strategic_plans_last_refreshed 
ON weekly_strategic_plans(last_refreshed_at DESC);
```

### Phase 3: Unified Caching Strategy

**Weekly Strategic Plan Service** (`weekly_strategic_plan_service.py`):

1. **Add cache check before generation** (similar to trade advisor pattern):
   ```python
   async def get_latest_weekly_plan(self, force_refresh: bool = False) -> dict | None:
       cache_key = f"{CACHE_PREFIX}:latest"
       
       # Check cache first (unless force refresh)
       if not force_refresh:
           cache = get_cache()
           cached = await cache.get(cache_key)
           if cached:
               return json.loads(cached)
       
       # Generate new plan...
   ```

2. **Update database operations** to include refresh timestamp:
   ```sql
   ON CONFLICT ON CONSTRAINT uq_weekly_plan_week_version
   DO UPDATE SET
       -- ... existing fields ...
       last_refreshed_at = NOW(),  # Add this line
       updated_at = NOW()
   ```

3. **Cache generated results** with 2-hour TTL (matching trade advisor):
   ```python
   await cache.set(cache_key, json.dumps(response_data), ttl=CACHE_TTL)
   ```

### Phase 4: Response Standardization

**Weekly Strategic Plan Service** - Update API responses to include refresh timestamp:
```python
# In _row_to_dict() method (line 2133+)
result = {
    # ... existing fields ...
    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    "last_refreshed_at": row["last_refreshed_at"].isoformat() if row["last_refreshed_at"] else None,
    "model_used": row["model_used"],  # Now contains actual model name
}
```

**Trade Advisor Service** - Ensure generated_at is included in fresh results:
```python
# In get_latest_briefing() response (line 2255-2277)
result = {
    # ... existing fields ...
    "generated_at": datetime.now(UTC).isoformat(),  # Add this line
    "model": ai_result["model"],  # Now contains actual model name
}
```

### Phase 5: Frontend Improvements

**AdvisorBriefingPanel.tsx** (`frontend/src/components/planner/AdvisorBriefingPanel.tsx`):

1. **Enhanced model mapping** (lines 578-586):
   ```typescript
   const friendlyModelName = (model: string) => {
     const map: Record<string, string> = {
       'minimax-m2.7': 'MiniMax M2.7',
       'MiniMax-M2.7': 'MiniMax M2.7',
       'kimi-k2.6': 'Kimi K2.6',
       'kimi-k2.5': 'Kimi K2.5',  // Legacy support
       'qwen3-coder-next': 'ADA Local',
       'ollama-router': 'ADA Local',
       'ollama-planning': 'ADA Local',  // Legacy support
       'qwen3.5:35b-a3b': 'ADA Local',
       'qwen3.6:35b-a3b-q4_K_M': 'ADA Local',
     };
     return map[model] || `${model} (Local)`;  // Better fallback
   };
   ```

**WeekAheadPanel.tsx** (`frontend/src/components/planner/WeekAheadPanel.tsx`):

1. **Add timestamp display** (similar to AdvisorBriefingPanel):
   ```typescript
   // Use last_refreshed_at if available, fallback to created_at
   const displayTime = plan.last_refreshed_at || plan.created_at;
   const timeLabel = plan.last_refreshed_at ? 'Updated' : 'Created';
   ```

2. **Add model info to footer** (consistent with advisor panel):
   ```typescript
   <div className="text-xs text-muted-foreground">
     {timeLabel}: {formatRelativeTime(displayTime)} | 
     {friendlyModelName(plan.model_used)} | 
     ${Number(plan.cost_usd || 0).toFixed(4)}
   </div>
   ```

### Phase 6: Documentation Updates

**Weekly Strategic Plan Service** (`weekly_strategic_plan_service.py`):
```python
# Line 18: Update documentation
"""
Output: Structured WeeklyStrategicPlanResponse via MiniMax M2.7 (PLANNING task type)
Stored in weekly_strategic_plans table with versioning.
"""

# Line 186-187: Update comments
# Use centralized router (MiniMax M2.7 cloud / Ollama local fallback)
```

## Verification Plan

**Backend Testing:**
1. **API Response Verification**:
   ```bash
   # Test trade advisor refresh
   curl -X POST "http://localhost:8006/api/trade-advisor/generate?force=true"
   # Verify: response includes actual model name (not "ollama-router")
   
   # Test weekly plan refresh  
   curl -X POST "http://localhost:8006/api/weekly-plan/generate" -d '{"force": true}'
   # Verify: response includes actual model name and last_refreshed_at timestamp
   ```

2. **Database Verification**:
   ```sql
   -- Check that refresh timestamps are updating
   SELECT id, created_at, last_refreshed_at, model_used 
   FROM weekly_strategic_plans 
   ORDER BY last_refreshed_at DESC LIMIT 5;
   
   -- Check trade advisor timestamps
   SELECT briefing_type, briefing_date, generated_at, model 
   FROM trade_advisor_briefings 
   ORDER BY generated_at DESC LIMIT 5;
   ```

**Frontend Testing:**
1. **Browser Testing**: Navigate to `/trade-planner`, verify both panels show correct model names and timestamps
2. **Refresh Testing**: Click refresh buttons, verify timestamps update and show "just now" or recent times
3. **Model Display**: Verify friendly names show "MiniMax M2.7" instead of "Kimi 2.5" or raw model strings

**Cache Testing:**
1. **Cache Behavior**: First API call should hit LLM, second call within 2 hours should return cached (verify via logs)
2. **Force Refresh**: `force=true` parameter should bypass cache and generate fresh content
3. **Cache Invalidation**: Verify old cache entries expire after 2 hours

## Critical Files Modified

- `backend/services/trade_advisor_service.py` - LLM routing fix, response enhancement
- `backend/services/weekly_strategic_plan_service.py` - LLM routing fix, caching addition, timestamp handling  
- `backend/alembic/versions/[new]_add_refresh_timestamps.py` - Database migration
- `frontend/src/components/planner/AdvisorBriefingPanel.tsx` - Model mapping enhancement
- `frontend/src/components/planner/WeekAheadPanel.tsx` - Timestamp display, model info addition

## Expected Outcomes

After implementation:
1. **Correct Model Attribution**: Both panels show "MiniMax M2.7" when cloud model is used
2. **Accurate Timestamps**: Fresh refreshes show "just now" or recent times, not "40d ago"
3. **Consistent Caching**: Both services cache intelligently but refresh when requested
4. **Improved Parsing**: Better LLM responses due to correct task routing to cloud models
5. **Unified Experience**: Both weekly plan and trade advisor panels behave consistently

This comprehensive fix addresses all root causes while maintaining backward compatibility and improving system reliability.