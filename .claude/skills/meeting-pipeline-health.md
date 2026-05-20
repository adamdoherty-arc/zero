---
name: meeting-pipeline-health
description: Daily health audit of the meeting steward subsystem. Pings recording, transcript, summary, vault-write, notification fan-out, and wake-word fire counts; grades the pipeline 0-100 and writes the result to legion_loop_runs.
mode: read-only
schedule: daily 07:30 UTC
---

# Meeting Pipeline Health

Run this skill once a day to catch silent failures across the Zero meeting
steward — these failures are easy to miss because there's no obvious user
complaint until they pile up over a week.

## What to check

1. **Recording pipeline** — `GET /api/meeting-recordings/capabilities` returns
   `can_record: true`. `GET /api/meeting-recordings/devices` lists at least
   one Reachy USB mic AND at least one WASAPI loopback device.
2. **Transcript backlog** — `SELECT COUNT(*) FROM meetings WHERE status =
   'processing' AND created_at < now() - interval '1 hour'`. Any non-zero
   means transcription is stuck and needs investigation.
3. **Vault write** — for the last 24 h of completed meetings, verify
   `/vault/00_Meta/_agent/memory_vault/meetings/` (or wherever the
   memory_tree service decided) has a file with matching `meeting_id`.
4. **Notification bus** — `POST /api/notifications/publish` with a
   synthetic event, then `GET /api/notifications/recent?limit=5` must show
   it. Failure = the in-process bus singleton went sideways during a hot
   reload.
5. **Wake-word fire count** — count `voice_heard` events in
   `workspace/reachy/companion_events.json` in the last 24 h. Zero fires
   in 24 h is suspicious — either the wake loop is dead or the threshold
   needs tuning.
6. **Companion policy sanity** — `GET /api/reachy/companion/policy` must
   include the new fields `transcribe_only`, `meeting_active`,
   `last_wake_at`, `wake_response_window_s`. Missing = old build or
   broken model.
7. **host_agent reachable** — `GET host_agent:18796/health` returns
   `ok: true` and `wake.mode` matches expected backend.

## Grading

100 = all 7 pass. Deduct 10 per failing check; flag composite < 60 as
RED for the mesh-coordinator daily report.

## Output

Write findings to `legion_loop_runs` with `loop_id=meeting-pipeline-health`,
along with the per-check evidence (counts, recent failures, suggested fix).
Failed checks should propose the next sprint task — e.g. "transcription
backlog: 12 meetings stuck, restart meeting_processing_pipeline service".

## Cross-references

- Meeting Steward architecture: `C:\Users\hadam\.claude\projects\c--code-zero\memory\reference_meeting_steward.md`
- Notification bus: `backend/app/services/notification_bus.py`
- Companion policy: `backend/app/models/reachy_companion.py`
- host_agent health: `host_agent/main.py:health` (mounted at `/health`)
