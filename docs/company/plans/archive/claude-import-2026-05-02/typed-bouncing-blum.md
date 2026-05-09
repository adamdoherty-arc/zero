# Plan: Auto-Trigger Advisor Briefing After Robinhood Sync

## Context

Currently, Robinhood portfolio sync runs every 15 minutes in the background, but the ADA Portfolio Advisor briefing is manual-only (user clicks "Generate Now"). The user wants:
1. Sync interval changed to **30 minutes**
2. Each successful sync **automatically triggers** a new advisor briefing

This ensures the advisor always reflects the latest portfolio state without manual intervention.

## Changes

### File: `backend/services/positions_sync_service.py`

**1. Change sync interval (line 85-86)**
```python
# FROM:
SYNC_INTERVAL_SECONDS = 15 * 60

# TO:
SYNC_INTERVAL_SECONDS = 30 * 60
```
Update comment and module docstring to say 30 minutes.

**2. Add advisor trigger method to `PositionsSyncService` class (after line ~1162)**

New method `_trigger_advisor_briefing()`:
- Calls `get_market_session()` to determine current session
- Maps session to briefing type: `premarket` -> `pre_market`, `regular` -> `during_market`, `afterhours` -> `post_market`, `closed` -> skip
- Lazy-imports `get_trade_advisor_service` to avoid circular deps
- Launches `generate_briefing(briefing_type)` as a fire-and-forget background task using existing `_create_tracked_task()` pattern
- Wrapped entirely in try/except - advisor failure never affects sync
- Logs the trigger result

**3. Call the trigger after sync success (after line 1108)**

Insert after alert checking, before the return dict:
```python
advisor_result = await self._trigger_advisor_briefing()
```
Add `"advisor_trigger": advisor_result` to the return dict.

### No other files need changes

- `trade_advisor_service.py` - No changes needed. `generate_briefing(briefing_type)` already works as a standalone async call with its own cost cap enforcement.
- `backend/config.py` - Not needed. Keeping it simple with a constant.
- Frontend - No changes needed. The advisor panel already polls for latest briefings with `refetchInterval`, so it will pick up the auto-generated briefings automatically.

## Key Design Decisions

- **Fire-and-forget**: Briefing generation takes 30-120s (Kimi K2.5). Using `_create_tracked_task()` so sync returns immediately.
- **Market-hours aware**: No briefing during `closed` hours (8 PM - 4 AM ET, weekends).
- **Cost cap respected**: `generate_briefing()` already enforces the $5/day cap internally - no extra check needed.
- **Lazy import**: `from backend.services.trade_advisor_service import get_trade_advisor_service` inside the method to prevent circular imports.

## Verification

1. `docker restart ada-backend`
2. `docker logs ada-backend --tail 30` - confirm startup with no errors
3. Trigger a manual sync via `POST http://localhost:8006/api/portfolio/sync/trigger`
4. Check logs for `advisor_briefing_triggered` or `advisor_briefing_skipped` (depending on market hours)
5. If during market hours: verify new briefing appears at `GET http://localhost:8006/api/trade-advisor/latest`
