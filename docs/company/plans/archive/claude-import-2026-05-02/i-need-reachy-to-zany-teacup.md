# Add T-10 minute meeting announcement to Reachy

## Context

Reachy already announces upcoming calendar events at **T-5** and **T-1** minutes via the `reachy_calendar_nudge` scheduler job (runs every minute, checks the next hour of primary-calendar events, speaks through Reachy TTS). The user wants a third warning at **T-10** so they can wrap up deep work and prep.

No new infrastructure needed. The existing job already:
- Fetches events from the primary (work) calendar through `calendar_service.list_events()` using a 60-minute lookahead — already covers T-10.
- Deduplicates announcements per `(event_id, bucket)` so each warning fires exactly once.
- No-ops cleanly when Reachy daemon is offline.

The change is adding one bucket and one text template.

## Files to modify

Only one file: [backend/app/services/scheduler_service.py](backend/app/services/scheduler_service.py)

### Change 1 — add T-10 bucket in `_run_reachy_calendar_nudge` ([scheduler_service.py:1534-1550](backend/app/services/scheduler_service.py#L1534-L1550))

Currently:
```python
mins_until = (start_dt - datetime.now(tz=timezone.utc)).total_seconds() / 60.0
bucket = None
if 4.0 <= mins_until <= 5.5:
    bucket = 5
elif 0.5 <= mins_until <= 1.5:
    bucket = 1
if bucket is None:
    continue
...
text = (
    f"Heads up — {title} starts in one minute."
    if bucket == 1
    else f"Reminder — {title} starts in five minutes."
)
```

Change to:
```python
mins_until = (start_dt - datetime.now(tz=timezone.utc)).total_seconds() / 60.0
bucket = None
if 9.0 <= mins_until <= 10.5:
    bucket = 10
elif 4.0 <= mins_until <= 5.5:
    bucket = 5
elif 0.5 <= mins_until <= 1.5:
    bucket = 1
if bucket is None:
    continue
...
if bucket == 1:
    text = f"Heads up — {title} starts in one minute."
elif bucket == 5:
    text = f"Reminder — {title} starts in five minutes."
else:  # bucket == 10
    text = f"Coming up — {title} starts in ten minutes."
```

Bucket widths stay at ~1.5 min (matches the existing pattern, absorbs the every-minute cron jitter).

### Change 2 — update the docstring ([scheduler_service.py:1485-1488](backend/app/services/scheduler_service.py#L1485-L1488))

`"5 or 1 minute away"` → `"10, 5, or 1 minute away"`

### Change 3 — update the job registry description ([scheduler_service.py:111](backend/app/services/scheduler_service.py#L111))

`"Speak an upcoming-event warning through Reachy at 5/1 minute marks"` → `"Speak an upcoming-event warning through Reachy at 10/5/1 minute marks"`

## Reuse notes

- `reachy_service.say()` ([backend/app/services/reachy_service.py:512](backend/app/services/reachy_service.py#L512)) handles synth + upload + play + cleanup. No changes.
- `calendar_service.list_events()` already returns the 60-minute window. No changes.
- `self._reachy_nudged_events` dedup dict with 1-hour GC ([scheduler_service.py:1480, 1514-1516](backend/app/services/scheduler_service.py#L1480)) auto-absorbs the new `(event_id, 10)` keys with no additional bookkeeping.

## Deployment

Per [CLAUDE.md](CLAUDE.md), backend code is COPY'd into `zero-api` — rebuild required:

```bash
docker compose -f docker-compose.sprint.yml build --no-cache zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api
docker ps --format "table {{.Names}}\t{{.Status}}" | grep zero-api
```

## Verification

1. **Confirm the job is running** after restart:
   ```bash
   docker logs zero-api 2>&1 | grep reachy_calendar_nudge
   ```
   Should see the job registered at startup.

2. **Live test** — create a calendar event ~11 minutes in the future on the primary Google account, then watch:
   ```bash
   docker logs -f zero-api 2>&1 | grep -E "reachy_calendar_nudge|reachy_calendar_nudge_spoken"
   ```
   Expect three spoken-event log lines: `bucket_min=10`, then `=5`, then `=1`, each about a minute apart before the event starts.

3. **Offline-safe** — if the Reachy daemon is down, the job exits silently at the `is_connected()` check — verified by the existing pattern, no regression risk.

## Out of scope

- **Per-calendar filtering** — today the sync only pulls the `primary` calendar for each connected Google account, which is the user's work calendar. No filter change needed. If the user later connects a second account and wants to exclude a personal one, that's a separate feature on `calendar_service.sync_events` (line ~490).
- **User-configurable warning offsets** — buckets are hardcoded. Parameterizing into settings can be done later if 10/5/1 turns out to be wrong.
