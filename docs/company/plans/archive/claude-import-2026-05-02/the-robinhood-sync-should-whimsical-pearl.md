# Plan: Automated 15-Minute Robinhood Sync

## Context

The user wants the Robinhood portfolio sync to happen automatically every 15 minutes instead of requiring manual button presses. They also want all portfolio values on the page to update automatically when the sync completes.

Currently, the system has:
- **Manual sync**: "Sync Robinhood" button calls `POST /api/portfolio/sync`
- **Automatic sync**: Background `PositionsSyncService` that syncs every **30 minutes**
- **Real-time updates**: WebSocket broadcasting that updates UI when sync completes
- **Comprehensive error handling**: Rate limiting, device approval flows, and progress tracking

The good news is that most of the automation infrastructure already exists! The system just needs the sync interval adjusted from 30 minutes to 15 minutes, and the UI already has real-time update capabilities.

## Recommended Approach

### Option 1: Simple Configuration Change (Recommended)
Modify the existing `PositionsSyncService` to use 15-minute intervals instead of 30-minute.

**Pros:**
- Minimal code changes (1-2 lines)
- Leverages existing robust infrastructure
- Maintains all existing error handling and rate limiting
- UI updates already work via WebSocket

**Cons:**
- Less flexible than a separate scheduler

### Option 2: User-Configurable Sync Interval
Add a configuration setting that allows users to choose their sync interval (5, 15, 30, 60 minutes).

**Pros:**
- Maximum flexibility
- Can accommodate different user preferences
- Still uses existing infrastructure

**Cons:**
- Slightly more complex implementation
- Need to add settings UI

## Implementation Plan

### Phase 1: Update Sync Interval (Core Change)

**File:** `backend/services/positions_sync_service.py`
- **Current:** `SYNC_INTERVAL_SECONDS = 30 * 60  # 30 minutes`
- **Change to:** `SYNC_INTERVAL_SECONDS = 15 * 60  # 15 minutes`

### Phase 2: Add Configuration Support (Optional Enhancement)

**Files to modify:**
1. `backend/services/positions_sync_service.py` - Accept configurable interval
2. `backend/config.py` - Add ROBINHOOD_SYNC_INTERVAL_MINUTES environment variable  
3. `frontend/src/components/SyncStatusPanel.tsx` - Add interval selection in settings
4. `backend/routers/settings.py` - Add endpoint to update sync interval

### Phase 3: Enhanced UI Feedback

**File:** `frontend/src/components/SyncStatusPanel.tsx`
- Show "Next auto-sync in: X minutes" countdown
- Display current sync interval setting
- Add option to trigger immediate sync

## Detailed Implementation

### Backend Changes

#### 1. Update `PositionsSyncService` Constructor
```python
def __init__(self, sync_interval_minutes: int = 15):
    # Store interval in minutes for easier configuration
    self.sync_interval_seconds = sync_interval_minutes * 60
    self._last_sync: datetime | None = None
    # ... existing code
```

#### 2. Make Interval Configurable via Environment
```python
# In config.py
ROBINHOOD_SYNC_INTERVAL_MINUTES: int = Field(default=15, ge=5, le=120)

# In positions_sync_service.py
from backend.config import get_config

def get_positions_sync_service() -> PositionsSyncService:
    if not hasattr(get_positions_sync_service, '_instance'):
        config = get_config()
        get_positions_sync_service._instance = PositionsSyncService(
            sync_interval_minutes=config.ROBINHOOD_SYNC_INTERVAL_MINUTES
        )
    return get_positions_sync_service._instance
```

#### 3. Add Settings API Endpoint
```python
# In backend/routers/settings.py
@router.post("/robinhood/sync-interval")
async def update_sync_interval(interval_minutes: int) -> dict[str, Any]:
    """Update Robinhood auto-sync interval (5-120 minutes)"""
    if not (5 <= interval_minutes <= 120):
        raise HTTPException(400, "Interval must be 5-120 minutes")
    
    # Update service
    sync_service = get_positions_sync_service()
    await sync_service.update_sync_interval(interval_minutes)
    
    return {"success": True, "interval_minutes": interval_minutes}
```

### Frontend Changes

#### 1. Add Interval Display to SyncStatusPanel
```tsx
// Show current interval and countdown
<div className="flex items-center justify-between text-sm text-slate-400">
    <span>Auto-sync every {syncInterval} minutes</span>
    <span>Next sync in: {nextSyncCountdown}</span>
</div>
```

#### 2. Add Interval Selector in Settings
```tsx
<Select value={syncInterval} onValueChange={handleIntervalChange}>
    <SelectItem value="5">5 minutes</SelectItem>
    <SelectItem value="15">15 minutes</SelectItem>
    <SelectItem value="30">30 minutes</SelectItem>
    <SelectItem value="60">1 hour</SelectItem>
</Select>
```

### WebSocket Integration (Already Working)

The existing WebSocket infrastructure will automatically handle UI updates:

**Current Flow:**
1. Background sync completes every 15 minutes
2. `PositionsSyncService` broadcasts `sync_complete` message via WebSocket
3. Frontend `useUnifiedWebSocket` receives message  
4. React Query caches are invalidated automatically
5. UI components re-render with fresh data

**No changes needed** - this flow already works perfectly.

## Verification Plan

### 1. Backend Testing
```bash
# Verify sync interval change
docker restart ada-backend
curl http://localhost:8006/api/portfolio/sync-status
# Should show 15-minute intervals in logs

# Check sync happens every 15 minutes
docker logs ada-backend --tail 50 -f
# Watch for "Starting scheduled portfolio sync" messages
```

### 2. Frontend Testing  
```bash
# Start frontend and verify auto-updates
cd frontend && pnpm test:e2e -- --grep "auto-sync"

# Manual verification:
# 1. Open portfolio page
# 2. Wait 15 minutes
# 3. Verify portfolio data updates without manual action
# 4. Check WebSocket messages in browser dev tools
```

### 3. End-to-End Verification
1. Portfolio data should refresh every 15 minutes automatically
2. UI should show updated P&L, positions, and equity values
3. No manual button pressing required
4. Sync status panel should show "Next sync in: X minutes"
5. Rate limiting and error handling should continue to work

## Edge Cases & Error Handling

### Rate Limiting
- **Current**: Respects Robinhood rate limits with progressive cooldowns
- **Change**: None needed - existing rate limit handling will work with 15-minute intervals
- **Risk mitigation**: More frequent syncing may hit rate limits more often, but existing exponential backoff will handle this

### Authentication Failures  
- **Current**: Device approval flow already handles re-authentication
- **Change**: None needed - existing auth flows work with any interval
- **Risk mitigation**: Shorter intervals mean faster detection of auth issues

### Market Hours
- **Enhancement opportunity**: Could sync more frequently during market hours (15 min) and less frequently after hours (30-60 min)
- **Implementation**: Add market hours detection to sync interval logic

## Rollback Plan

If 15-minute syncing causes issues:
1. Change `SYNC_INTERVAL_SECONDS = 30 * 60` back to 30 minutes
2. Restart backend: `docker restart ada-backend`
3. System reverts to previous behavior immediately

## Success Criteria

✅ **Portfolio sync happens automatically every 15 minutes**
✅ **All UI values update without manual button presses**  
✅ **WebSocket updates continue to work for real-time feedback**
✅ **Rate limiting and error handling remain robust**
✅ **No performance degradation or increased error rates**
✅ **User can still manually sync if needed**

The implementation leverages existing, well-tested infrastructure and requires minimal code changes while providing the exact functionality the user requested.