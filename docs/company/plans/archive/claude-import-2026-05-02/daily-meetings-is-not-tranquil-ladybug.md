# Retire DailyMeetings standalone — run meetings end-to-end inside Zero

## Context

The Reachy Meetings page shows `DailyMeetings host service isn't responding` because nginx proxies every `/api/meeting*` and `/ws/meeting-*` path to `host.docker.internal:18793`, and no DailyMeetings process is running there. The deeper problem: **it shouldn't need to**.

Zero's backend already owns the full meeting pipeline in-container — CRUD ([routers/meetings.py](backend/app/routers/meetings.py)), transcription ([services/meeting_transcription_service.py](backend/app/services/meeting_transcription_service.py)), diarization, summary/action-items ([services/meeting_summary_service.py](backend/app/services/meeting_summary_service.py)), hybrid search, RAG chat, processing pipeline with WebSocket progress ([routers/meeting_ws.py](backend/app/routers/meeting_ws.py)), and auto-record scheduling ([services/meeting_auto_recorder_service.py](backend/app/services/meeting_auto_recorder_service.py)). The only thing Docker can't do is grab Windows audio — and that's already handled by **host_agent** on `:18794` via `/record/start`, `/record/stop`, `/record/status`, `/devices`, `/ws/meeting-live-transcript` (host_agent already proxies the live transcript from its WASAPI capture).

So the DailyMeetings box on `:18793` is dead code in an architecture that moved on. We just need to cut it out, point traffic at the places that already exist, and then walk the end-to-end flow to confirm record → transcribe → summarize (with action items) → save works, and that the upcoming-meeting announcement fires through Reachy.

Outcome: open Reachy Meetings page, hit "Quick meeting", speak for a minute, stop — and get back a durable meeting record with transcript, summary, action items, recommendations, searchable + chattable, with Reachy announcing the next calendar meeting a minute before it starts.

---

## Files to change

**Frontend (nginx + WS client):**
- [frontend/nginx.conf](frontend/nginx.conf) — repoint `/api/meetings(/|$)`, `/api/meeting-recordings(/|$)`, `/api/meeting-transcriptions(/|$)`, `/api/meeting-summaries(/|$)`, `/api/meeting-search(/|$)`, `/api/meeting-chat(/|$)`, and the three `/ws/meeting-*` blocks all from `host.docker.internal:18793` → `zero-api:18792`. Delete the now-redundant exact-match `= /api/meetings/dailymeetings-health` block (the regex blocks will cover it). Keep `absolute_redirect off` and the `Upgrade/Connection` headers on the WS blocks.
- [frontend/src/hooks/useMeetingWebSocket.ts](frontend/src/hooks/useMeetingWebSocket.ts) — drop the hardcoded `:18793` base. Build WS URLs off `window.location.host` (same origin as the page) so nginx handles the proxy like every other API call. Update the file-header comment.

**Frontend (dead health UI):**
- [frontend/src/pages/ReachyMeetingsPage.tsx](frontend/src/pages/ReachyMeetingsPage.tsx) — remove the `DailyMeetings host service isn't responding` banner (lines ~118-141), the `useDailyMeetingsHealth()` hook call, and the `!dmHealth.data?.ok` gate on "Quick Meeting". Replace the gate with `useRecordingCapabilities()` → `.can_record` (already exists in [useMeetings.ts](frontend/src/hooks/useMeetings.ts)); that's the correct probe (host_agent :18794) anyway.
- [frontend/src/hooks/useMeetings.ts](frontend/src/hooks/useMeetings.ts) — delete the `useDailyMeetingsHealth` hook export.

**Backend (dead health endpoint + setting):**
- [backend/app/routers/meetings.py](backend/app/routers/meetings.py) — delete `@router.get("/dailymeetings-health")` (lines 179-198).
- [backend/app/infrastructure/config.py](backend/app/infrastructure/config.py) — remove the `dailymeetings_url` setting.
- Grep `backend/` for any other `dailymeetings_url` / `DAILYMEETINGS_URL` readers and remove.

**Backend (scheduler bugfix — surface only if manual E2E proves it's broken):**
- [backend/app/services/scheduler_service.py](backend/app/services/scheduler_service.py) `_run_reachy_meeting_auto_record` (line ~1633) calls `start_recording(db, meeting_id, source="mixed")` directly. In Docker, `start_recording` tries to grab audio locally and will fail. The manual `/meetings/{id}/record-now` path already does the right thing — `_host_agent_url() → _forward(...)`. Extract that check so both entrypoints route through host_agent when `ZERO_HOST_AGENT_URL` is set. If the E2E test confirms auto-record already works via some other path, skip this.

**Docker-compose env (verify, don't rewrite unless missing):**
- [docker-compose.sprint.yml](docker-compose.sprint.yml) — confirm `ZERO_HOST_AGENT_URL=http://host.docker.internal:18794` is set on `zero-api`. If missing, add it.

**NOT changing (already correct):**
- `backend/app/routers/meeting_recordings.py` — already forwards recording start/stop/status/devices to host_agent :18794 when `ZERO_HOST_AGENT_URL` is set; falls back to in-container capture otherwise. Good as-is.
- `backend/app/services/meeting_processing_pipeline.py` — already translates host_agent recording paths to container-visible paths. Good as-is.
- `host_agent/` — no changes. It's the correct owner of WASAPI audio capture + live transcript WS.
- C:\code\DailyMeetings — leave the standalone on-disk. We're not deleting the repo in this pass; we're just cutting it out of Zero's request graph. If the user wants the code deleted later, that's a follow-up.

---

## Announcement path (verify, don't rebuild)

Announcement is already wired:
- `reachy_calendar_nudge` scheduler job (scheduler_service.py ~line 1479) tracks `(event_id, bucket)` and speaks an upcoming-meeting announcement when an event is ~1 minute away and hasn't been announced yet.
- `reachy_meeting_auto_record` fires at event start, calls `reachy.say(f"Recording {title} now.")`, and begins recording for any meeting flagged via `/meetings/{id}/auto-record`.

What to verify during E2E:
1. Both jobs are registered and running (check `GET /scheduler/status` or scheduler logs).
2. Quiet hours config isn't suppressing announcements in the test window.
3. Reachy daemon + TTS path is alive (same `DaemonPanel` on the Motion Library page).

If the nudge job isn't announcing, that's a separate bug to file, not a scope expansion here.

---

## Vault save (verify, small hook if missing)

SecondBrain plan says meeting summaries should land in the Obsidian vault. Check whether `meeting_processing_pipeline` (or `meeting_summary_service`) already writes to `/vault/.../meetings/` after summary generation. If not, add a thin hook at the end of the pipeline: export the same markdown that `GET /meetings/{id}/export` produces into `/vault/02_Meetings/{YYYY-MM-DD}-{slug}.md`. Re-use existing vault_service write helpers — don't write a new filesystem layer.

This is the only new code in the plan; everything else is deletion + re-pointing.

---

## Verification (run in order)

### 1. Pre-flight — host_agent + recording capability
```bash
# From Windows host (outside Docker):
curl http://localhost:18794/health
curl http://localhost:18794/devices

# From inside zero-api container:
docker exec zero-api curl -s http://host.docker.internal:18794/health
docker exec zero-api curl -s http://host.docker.internal:18792/api/meeting-recordings/capabilities
```
Expect `can_record: true`. If host_agent is down, start it: `cd c:/code/zero/host_agent && run.bat`.

### 2. Rebuild + bring up
```bash
docker compose -f docker-compose.sprint.yml build zero-ui zero-api
docker compose -f docker-compose.sprint.yml up -d zero-ui zero-api
docker ps --format "table {{.Names}}\t{{.Status}}" | grep zero
```

### 3. Confirm the nginx repointing
From the host:
```bash
curl -s http://localhost:5173/api/meetings/ | head -c 200
curl -s http://localhost:5173/api/meeting-recordings/capabilities
```
Both should return Zero's JSON, not a 502 or "upstream unreachable".

### 4. Record → transcribe → summarize E2E
Open http://localhost:5173/reachy/meetings:
- Banner gone. "Quick Meeting" enabled.
- Click Quick Meeting → pick mic → Start.
- Speak ~60s of structured content (mention a decision, an action item with an owner, a question for later).
- Watch the live transcript WebSocket populate in real time.
- Click Stop. Processing WS should walk through transcribe → diarize → store → summarize → embed.

Verify in the UI + DB:
```bash
docker exec zero-postgres psql -U postgres -d zero -c "SELECT id,title,status,duration_seconds FROM meetings ORDER BY created_at DESC LIMIT 3;"
docker exec zero-postgres psql -U postgres -d zero -c "SELECT COUNT(*) FROM meeting_transcript_segments WHERE meeting_id=(SELECT id FROM meetings ORDER BY created_at DESC LIMIT 1);"
docker exec zero-postgres psql -U postgres -d zero -c "SELECT LEFT(summary_text,200), action_items FROM meeting_summaries ORDER BY created_at DESC LIMIT 1;"
```
Expect: non-zero transcript segments, a summary containing the decision you spoke, `action_items` JSONB with the owner you named.

### 5. Search + chat round-trip
- `/reachy/meetings` search box: search for a word you spoke. Expect a hit.
- Open the meeting → chat tab → ask "what did we decide?". Expect the LLM to cite the decision.

### 6. Announce path
- Create a calendar event 2 minutes out (via `POST /api/calendar/events` or Google Calendar sync).
- `POST /meetings/from-event` with the event id, then `POST /meetings/{id}/auto-record {"enabled": true}`.
- At ~T-60s: Reachy should speak the upcoming-meeting line (`reachy_calendar_nudge`).
- At T-0: Reachy should say "Recording {title} now." and a new meeting should go into `recording` status.
- At event end: it should stop, run the pipeline, end up in `completed`.

Watch logs:
```bash
docker logs -f zero-api 2>&1 | grep -E "reachy_calendar_nudge|reachy_meeting_auto_record|reachy_meeting_auto_stop"
```

### 7. Vault artifact
If the vault-save hook is in scope:
```bash
ls -lt "/c/code/vault/ObsidianZero/02_Meetings/" | head -5
```
Should see a fresh markdown file for the meeting with summary + action items + transcript.

---

## Risks + rollback

- **nginx change is the load-bearing step.** If zero-api is returning 500s for `/api/meetings*`, the UI goes fully dark instead of showing the friendly DailyMeetings banner. Mitigation: keep `docker compose logs zero-api` open during cutover; revert the nginx.conf block if meeting endpoints throw on Zero's side. `git revert` gets the old proxy back in one commit.
- **host_agent must be running** on Windows for any new recording. Pre-flight step 1 catches this. If host_agent is wedged, the existing DaemonPanel (`/reachy` page) can restart it.
- **Auto-record in Docker** may currently bypass host_agent forwarding (scheduler calls `start_recording` directly). If step 6 fails with "audio device unavailable" from inside zero-api, that's the scheduler bug — fix it the same way `record-now` does: check `_host_agent_url()` first, `_forward("POST", "/record/start", ...)` if set.
- **SW caching** of the old frontend bundle could keep the WS client pointed at `:18793` after rebuild. Hard-refresh / clear SW on first manual test.

No destructive actions. Everything is code + config + rebuild. The standalone `C:\code\DailyMeetings` directory is untouched and can be formally retired in a follow-up once this has baked.
