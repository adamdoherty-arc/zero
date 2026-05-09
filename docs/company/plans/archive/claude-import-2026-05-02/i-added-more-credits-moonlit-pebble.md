# Fix ADA Portfolio Advisor to Use Kimi 2.6 Instead of MiniMax M2.7

## Context

The user added more credits to their Kimi 2.6 account and wants the ADA Portfolio Advisor to use Kimi 2.6 instead of the currently displayed MiniMax M2.7. They also want to ensure results are saved and that "Kimi 2.6" is displayed in the bottom of the UI when using it.

After comprehensive codebase exploration, I discovered:

1. **Critical Bug**: The `_resolve_kimi_model()` method in `trade_advisor_service.py` incorrectly reads `MINIMAX_MODEL` env var instead of `KIMI_MODEL`, causing it to use MiniMax even when attempting to use Kimi
2. **Routing Misconfiguration**: The centralized LLM router only uses local models for PLANNING tasks to avoid 429 errors, but the user wants to use the cloud Kimi service
3. **Persistence Already Works**: Results are correctly saved to database with ON CONFLICT DO UPDATE pattern
4. **UI Display Ready**: Frontend already has "Kimi 2.6" model name mapping

## Implementation Plan

### Phase 1: Fix Kimi Configuration Bug

**File**: `backend/services/trade_advisor_service.py`

**Current Issue (Line 1541)**:
```python
def _resolve_kimi_model(self) -> str:
    model = os.getenv("MINIMAX_MODEL", "MiniMax-M2.7")  # WRONG ENV VAR
```

**Fix**: Change to read the correct environment variable:
```python
def _resolve_kimi_model(self) -> str:
    model = os.getenv("KIMI_MODEL", "kimi-k2.6")
```

This fixes the primary Kimi fallback chain so that when `is_kimi_available()` returns True, the service actually uses Kimi instead of MiniMax.

### Phase 2: Update LLM Routing Table (Optional Enhancement)

**File**: `backend/infrastructure/llm_router.py`

**Current Configuration (Lines 213-231)**:
```python
TaskType.PLANNING: ["qwen3-chat"],  # Local only to avoid 429 errors
```

**Enhanced Configuration**:
```python
TaskType.PLANNING: ["kimi-k2.6", "qwen3-chat"],  # Kimi primary, local fallback
```

This ensures that even if the direct Kimi fallback fails, the centralized router will also try Kimi before falling back to local models.

### Phase 3: Verification and Testing

1. **Backend Health Check**: Verify Kimi API connectivity via `/api/system/llm-health`
2. **Generate Test Briefing**: Use `/api/trade-advisor/generate` with `force: true`
3. **Frontend Verification**: Check that model name displays as "Kimi 2.6" in bottom footer
4. **Cost Tracking**: Verify cost calculation uses Kimi pricing ($0.95/M input, $4.00/M output)
5. **Database Persistence**: Confirm briefing is stored with `model: "kimi-k2.6"`

### Phase 4: Environment Validation

**Verify Required Environment Variables**:
- `KIMI_API_KEY=sk-LgZTxjyJ3nBcRkQABtyLgDjpgozQVBKi1fUAy6TZzDsXDHLa` ✅ (Already configured)
- `KIMI_BASE_URL=https://api.moonshot.cn/v1` ✅ (Already configured)  
- `KIMI_MODEL=kimi-k2.6` ✅ (Already configured)

## Files to Modify

### Critical Files
1. **`backend/services/trade_advisor_service.py`** - Line 1541: Fix env var reference
2. **`backend/infrastructure/llm_router.py`** - Lines 213-231: Add Kimi to routing table

### Files to Read for Verification
1. **`frontend/src/components/planner/AdvisorBriefingPanel.tsx`** - Lines 578-596: Model name mapping (already has "Kimi 2.6")
2. **`backend/routers/trade_advisor.py`** - Generate endpoint for testing
3. **`.env`** - Verify Kimi configuration is present

## Current Architecture

The portfolio advisor uses a two-stage fallback:
1. **Stage 1**: Direct Kimi K2.6 call via `get_kimi_client()` 
2. **Stage 2**: Centralized router using `TaskType.PLANNING`

**Problem**: Stage 1 is broken due to env var bug, so it falls back to Stage 2 which uses local models only.

**Solution**: Fix Stage 1 to properly use Kimi, optionally enhance Stage 2 to also try Kimi.

## Result Persistence (Already Working)

The briefing persistence is correctly implemented:
- **Database**: `trade_advisor_briefings` table with unique constraint on `(briefing_type, briefing_date)`
- **Storage Pattern**: `ON CONFLICT DO UPDATE` - saves over last run for same day/type
- **Timestamps**: `generated_at` tracks when each version was created
- **Cache**: 2-hour Redis TTL for quick retrieval
- **Frontend**: Automatically displays latest briefing with correct model name

## Expected Outcome

After implementation:
1. Portfolio advisor will use Kimi 2.6 for briefing generation
2. UI will display "Kimi 2.6" in the bottom footer instead of "MiniMax M2.7"
3. Results will continue to be saved (already working)
4. Cost tracking will use Kimi pricing rates
5. Fallback to local models remains available if Kimi fails

## Verification Steps

1. Restart backend after changes: `docker restart ada-backend`
2. Check logs for Kimi connection: `docker logs ada-backend --tail 20`
3. Generate new briefing and verify model name in UI
4. Check database record has `model: "kimi-k2.6"`
5. Verify cost calculation reflects Kimi pricing