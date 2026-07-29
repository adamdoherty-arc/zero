---
name: meeting-pipeline-health
description: Daily health audit of the meeting steward subsystem. Pings recording, transcript, summary, vault-write, notification fan-out, and wake-word fire counts; grades the pipeline 0-100 and writes the result to legion_loop_runs.
mode: read-only
schedule: daily 07:30 UTC
owner_project: zero
category: ops-health
endpoint:
  method: GET
  url: http://host.docker.internal:18792/api/meeting-steward/
  auth: bearer
dispatch:
  via: mesh-coordinator
  cross_post_to: legion_loop_runs
  triggers_on_alarm: meeting.health.alarm
backend_job: meeting_pipeline_health
backend_cron: "*/15 * * * *"
---

# Meeting Pipeline Health

Run this skill once a day to catch silent failures across the Zero meeting
steward — these failures are easy to miss because there's no obvious user
complaint until they pile up over a week.

## What to check

1. **Recording pipeline** — `GET /api/meeting-recordings/capabilities` returns
   `can_record: true`. `GET /api/meeting-recordings/devices` lists at least
   one WASAPI loopback device.
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

Checks 5-7 (wake-word fire count, companion policy sanity, host_agent
reachable) were retired 2026-07-11 — robot/Reachy hardware control
(`host_agent`, `reachy_companion_service`, the wake-word loop) moved to a
separate app, Zero Studio. Meeting Steward's virtual-attendee driver
(`superhuman.py`, hosted in `host_agent`) went with it; this skill no longer
covers wake-triggered or virtual-attendee recording, only the
recording/transcript/vault/notification pipeline.

## Grading

100 = all 4 pass. Deduct 25 per failing check; flag composite < 60 as
RED for the mesh-coordinator daily report.

## Output

Write findings to `legion_loop_runs` with `loop_id=meeting-pipeline-health`,
along with the per-check evidence (counts, recent failures, suggested fix).
Failed checks should propose the next sprint task — e.g. "transcription
backlog: 12 meetings stuck, restart meeting_processing_pipeline service".

## Cross-references

- Meeting Steward architecture: `C:\Users\hadam\.claude\projects\c--code-zero\memory\reference_meeting_steward.md`
- Notification bus: `backend/app/services/notification_bus.py`
