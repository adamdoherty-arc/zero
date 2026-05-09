# Discord Notification System Overhaul

## Context

Three user-reported problems with the Discord notification system:
1. **Too many "ADA is online" messages** — bot sends one every time Discord.py reconnects (multiple times/day), with zero throttling
2. **Duplicated alert symbols** — same symbol notified multiple times from different sources (notification scheduler, smart rules, proactive advisor) with no cross-source dedup for Discord delivery
3. **Alert Hub alerts missing from Discord** — `alert_hub_service.py` (4800+ lines) has ZERO `event_bus.emit()` calls, so the Discord event consumer never receives Alert Hub alerts despite listening for them

## Changes

### 1. Remove "ADA is online" startup message entirely

**File:** [bot.py](backend/services/discord/bot.py)

- Delete the call to `await self._send_startup_message()` at line 171 in `on_ready()`
- Delete the entire `_send_startup_message()` method (lines 351-375)
- This message provides no actionable value — the bot is always expected to be online

### 2. Wire Alert Hub → EventBus → Discord

**File:** [alert_hub_service.py](backend/services/alert_hub_service.py)

This is the core fix. Add event emission inside `generate_high_conviction_notifications()` so alerts flow through the existing EventBus → Discord Event Consumer → Signal Gateway pipeline.

- Add a private `_emit_to_discord()` helper method that:
  - Gets the event bus via `get_event_bus()`
  - Uses `EventType.OPPORTUNITY_DETECTED` for standard alerts (score < 90)
  - Uses `EventType.ALERT_HIGH_PRIORITY` for high-priority alerts (score >= 90)
  - Includes `symbol`, `score`, `confidence` (= score), `strategy_type` (= source value), `direction`, `alert_type`, `title`, `message` in the payload
  - Wraps in try/except so failures never break notification generation

- Call `_emit_to_discord()` after successful DB insert at line 3940 (`generated.append(notification_data)`)

**Why `OPPORTUNITY_DETECTED` instead of `ALERT_TRIGGERED`:**
- `OPPORTUNITY_DETECTED` already maps to `SignalSource.ALERT_HUB` in event_consumer.py:484
- Routes to `"opportunities"` channel (line 81) — which has a 5/hr rate limit
- `ALERT_TRIGGERED` maps to `SignalSource.TECHNICAL` and routes to `"technical"` — wrong semantic channel for Alert Hub alerts
- `ALERT_HIGH_PRIORITY` routes to `"critical"` channel (line 51) — correct for truly high-score alerts

### 3. Add EventBus emit to smart rule notifications

**File:** [rule_action_executor.py](backend/services/rule_action_executor.py)

- In `_action_notify()` (line 122), after the existing `svc.send_notification()` call at line 132, add EventBus emission:
  - Use `EventType.ALERT_TRIGGERED` (smart rules are technical in nature)
  - Include `symbol`, `score`, `strategy_type="smart_rule"`, `confidence`, `alert_type="smart_rule"`
  - Wrap in try/except, never fail the action if emit fails

**Why this fixes duplication:** The Signal Gateway in `event_consumer.py:412-460` generates a fingerprint (SHA256 of symbol + strategy_type + direction + source_key) with a TTL-based dedup window. When the same symbol comes from both Alert Hub (`strategy_type=system`) and smart rules (`strategy_type=smart_rule`), they get different fingerprints — which is correct (they're different signals). But when the same symbol comes from Alert Hub twice (e.g., from real_time_alerts AND watchlist_alerts in the UNION), the existing `notification_hash` dedup at line 3870-3892 already prevents duplicate DB inserts, so only one EventBus emit occurs.

### 4. Add `"opportunities"` channel to `stale_alert_cleanup`

**File:** [stale_alert_cleanup.py](backend/services/discord/stale_alert_cleanup.py)

- Verify the stale cleanup loop covers the `"opportunities"` channel — add it if missing

## Files Modified (Summary)

| File | Change | Lines |
|------|--------|-------|
| `backend/services/discord/bot.py` | Remove `_send_startup_message()` + call | line 171, lines 351-375 |
| `backend/services/alert_hub_service.py` | Add `_emit_to_discord()` + call from `generate_high_conviction_notifications()` | New method, ~3940 |
| `backend/services/rule_action_executor.py` | Add EventBus emit after notification send | ~137 |
| `backend/services/discord/stale_alert_cleanup.py` | Verify opportunity channel coverage | Audit only |

## Existing Infrastructure Reused (No Changes Needed)

- **EventBus** ([event_bus.py](backend/infrastructure/event_bus.py)) — `Event` dataclass, `EventType` enum, `get_event_bus()`, `publish()` — all existing
- **Discord Event Consumer** ([event_consumer.py](backend/services/discord/event_consumer.py)) — already subscribes to `OPPORTUNITY_DETECTED` (→ opportunities channel) and `ALERT_HIGH_PRIORITY` (→ critical channel), routes through Signal Gateway for dedup
- **Signal Gateway** ([signal_gateway.py](backend/services/signal_gateway.py)) — already has `SignalSource.ALERT_HUB`, fingerprint-based SHA256 dedup with TTL, confidence threshold (80%), per-channel rate limits
- **Embed builders** ([opportunity_embed.py](backend/services/discord/embeds/opportunity_embed.py), [alert_embed.py](backend/services/discord/embeds/alert_embed.py)) — handle the payload format for opportunity and alert events

## What This Does NOT Change

- Notification scheduler's in-app notification flow (DB inserts) — untouched
- Existing event emitters (proactive_advisor_monitor, options_flow_agent, etc.) — untouched
- Signal Gateway config (TTLs, thresholds, rate limits) — untouched
- Discord channel routing map — untouched (already has all needed mappings)
- EventType enum — no new types needed

## Verification

1. **No startup message:** `docker restart ada-backend` → check Discord health channel → no "ADA is online" message. Verify `docker logs ada-backend --tail 30` shows `discord_bot_connected` log but no embed sent.

2. **Alert Hub → Discord:** Call `POST /api/alert-hub/generate-notifications` → check Discord `#opportunities` channel for new embeds. Verify events appear in `docker logs ada-backend | grep "alert_hub_event_published"`.

3. **Dedup:** Trigger alerts for the same symbol from multiple sources → verify only one Discord message per symbol per dedup window. Check `docker logs ada-backend | grep "signal_duplicate_skipped"`.

4. **Smart rules → Discord:** Trigger a smart rule match → verify it appears in Discord `#technical` channel. Check `docker logs ada-backend | grep "smart_rule_event_published"`.

5. **Rate limits hold:** Generate >5 alerts in one hour → verify the 6th is rate-limited (`docker logs ada-backend | grep "rate_limited"`).

6. **Existing tests pass:** `docker exec ada-backend python -m pytest backend/tests/test_notification_scheduler.py backend/tests/test_notification_e2e.py backend/tests/test_notification_delivery.py -x -q`
