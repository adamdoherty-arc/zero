# Reachy Meetings — make it feature-rich

## Context

`ReachyMeetingsPage` looks empty and the user thinks meetings is broken. Investigation shows the underlying pipeline is **fully wired** (host_agent on :18794 healthy with Reachy USB mic capture, faster-whisper live transcript, pyannote diarization, LLM summary with structured action items, scheduler auto-record job every 60s). The page is empty because **Google Calendar OAuth is not connected**: `GET /api/calendar/status` returns `{"connected":false, "calendars_count":0, "last_sync":null}`. With no events, there is nothing to render.

What the user actually wants on top of fixing the empty state:
- Calendar-fed upcoming meetings (already exists once OAuth is connected).
- Real-time transcribe + summarize + take notes (already exists).
- **Recognize the user as a specific speaker** ("me as the speaker") — this does NOT exist. Pyannote only outputs relative labels (SPEAKER_00/01). There is no voiceprint enrollment, no persistent speaker memory across meetings.
- Strong action-item extraction (already extracted) **plus** turn them into Zero tasks (does NOT exist).
- Make it as feature-rich as possible.

This plan ships the missing pieces in 6 phases. Phases 0 + 5 + 6 are UI / quality-of-life. Phases 1, 2, 3, 4 are real new capability.

## Critical files (existing)

- [backend/app/routers/meetings.py](backend/app/routers/meetings.py) — meeting CRUD + `/from-event`, `/auto-record`, `/record-now`
- [backend/app/routers/meeting_recordings.py](backend/app/routers/meeting_recordings.py) — start/stop forwarded to host_agent
- [backend/app/routers/meeting_speakers.py](backend/app/routers/meeting_speakers.py) — current per-meeting speaker label mapping
- [backend/app/routers/calendar.py](backend/app/routers/calendar.py) — OAuth + sync endpoints
- [backend/app/services/meeting_processing_pipeline.py](backend/app/services/meeting_processing_pipeline.py) — orchestrates transcription → diarization → summary
- [backend/app/services/meeting_diarization_service.py](backend/app/services/meeting_diarization_service.py) — pyannote pipeline (loads `pyannote/speaker-diarization`)
- [backend/app/services/meeting_summary_service.py](backend/app/services/meeting_summary_service.py) — map-reduce LLM summary, already emits `{summary_text, key_topics, action_items[{owner,description,due}], decisions}`
- [backend/app/services/scheduler_service.py](backend/app/services/scheduler_service.py) — `reachy_meeting_auto_record` (1 min), `reachy_meeting_auto_stop`, `calendar_check` (10 min)
- [backend/app/db/models.py:1315](backend/app/db/models.py#L1315) — `MeetingSpeakerMappingModel` (per-meeting only, no embedding)
- [host_agent/main.py](host_agent/main.py) — `/record/start`, `/record/stop`, `/ws/meeting-live-transcript`
- [host_agent/audio_capture.py](host_agent/audio_capture.py) — captures from Reachy mic
- [frontend/src/pages/ReachyMeetingsPage.tsx](frontend/src/pages/ReachyMeetingsPage.tsx) — calendar list page
- [frontend/src/components/reachy/LiveMeetingPanel.tsx](frontend/src/components/reachy/LiveMeetingPanel.tsx) — recording → processing → summary UI
- [frontend/src/components/reachy/MeetingCard.tsx](frontend/src/components/reachy/MeetingCard.tsx) — record-now / auto-record toggle per event
- [frontend/src/pages/ReachyVoiceSettingsPage.tsx](frontend/src/pages/ReachyVoiceSettingsPage.tsx) — host for the new enrollment UI

## Phase 0 — Fix the empty page (P0 unblock)

Goal: when the user opens ReachyMeetingsPage with no calendar connected, show a clear "Connect Google Calendar" CTA instead of "No events in the next 7 days." Auto-trigger sync on mount when connected but stale.

Changes in [frontend/src/pages/ReachyMeetingsPage.tsx](frontend/src/pages/ReachyMeetingsPage.tsx):
1. Add `useCalendarStatus()` hook (call `GET /api/calendar/status`).
2. When `status.connected === false`: render a large card with `Connect Google Calendar` button that opens `GET /api/calendar/auth/url` in a new tab.
3. When connected and `status.last_sync` is null or older than 10 min, fire `useSyncCalendar().mutate()` automatically (once) on mount.
4. Below the calendar list, render a **Recent meetings strip** (last 5 from `GET /api/meetings?status=completed&limit=5`) so the page never looks empty.

No backend work needed. Calendar OAuth endpoints already exist.

## Phase 1 — Primary-user voice enrollment ("recognize me")

Goal: user records 30 sec of speech once → all future meetings auto-label that voice as "Me" (or whatever display name the user chose) instead of `SPEAKER_00`.

Tech: pyannote already loads in `meeting_diarization_service.py`; pyannote's `Inference` API also produces 256-dim speaker embeddings. Use cosine similarity for matching (threshold 0.7 — pyannote ECAPA recommends ~0.7 for same-speaker).

Backend:
1. **DB migration** (new alembic file): `voiceprints` table — `id`, `display_name`, `embedding` (`Vector(256)` via pgvector — already installed per memory), `samples_seconds`, `created_at`, `is_primary` (one row only).
2. **Model**: add `VoiceprintModel` to [backend/app/db/models.py](backend/app/db/models.py) next to `MeetingSpeakerMappingModel`. Pydantic schemas in `backend/app/models/meeting.py`.
3. **Service**: new `backend/app/services/voiceprint_service.py` — `compute_embedding(audio_path)` (load pyannote `pyannote/embedding` once), `enroll(display_name, audio_path, is_primary)`, `match(embedding) -> (display_name, similarity) | None`, `list_all()`, `delete(id)`.
4. **Router**: new `backend/app/routers/voiceprints.py` — `POST /api/voiceprints/enroll` (accepts WAV upload + display_name + is_primary), `GET /api/voiceprints`, `DELETE /api/voiceprints/{id}`. Mount in [main.py](backend/app/main.py).
5. **Pipeline integration**: in [meeting_processing_pipeline.py](backend/app/services/meeting_processing_pipeline.py) after diarization, for each `SPEAKER_X` cluster compute the centroid embedding (re-call pyannote `Inference` on slices belonging to that label, average the embeddings). Match against `voiceprints` table — replace `speaker_label` with the matched `display_name` when similarity > 0.7. Persist as `MeetingSpeakerMappingModel` rows so the existing UI displays correctly.

Host agent ([host_agent/main.py](host_agent/main.py)):
1. New `POST /voice/enroll/start` — records 30 sec from Reachy mic to a temp WAV, then calls `POST {ZERO_API_URL}/api/voiceprints/enroll` with the file. Returns voiceprint id.
2. Reuses existing `audio_capture.py` infrastructure.

Frontend ([frontend/src/pages/ReachyVoiceSettingsPage.tsx](frontend/src/pages/ReachyVoiceSettingsPage.tsx)):
1. New "Voice Enrollment" section: list of enrolled identities with delete; "Enroll yourself" button → 30 sec countdown → calls host_agent `/voice/enroll/start` with display_name from current user (defaulting to "Me").
2. New hook `useVoiceprints()` in `frontend/src/hooks/useMeetings.ts`.

## Phase 2 — Persistent speaker memory across meetings

Goal: when the user manually relabels `SPEAKER_01 → "Bob"` in a past meeting, future meetings auto-recognize Bob.

Backend:
1. Extend [backend/app/routers/meeting_speakers.py](backend/app/routers/meeting_speakers.py) `PUT /api/meetings/{id}/speakers`: when a label is mapped to a non-empty display_name, also extract the centroid embedding for that cluster from the meeting's stored WAV (reuse `voiceprint_service.compute_embedding` over the cluster slices) and upsert into `voiceprints` (matching on display_name). Set `is_primary=False`.
2. The pipeline matching step from Phase 1 now picks these up automatically.

Frontend: no change required (the existing speaker-mapping UI in `MeetingDetailPage` keeps working — its edits now persist globally).

## Phase 3 — Action items become Zero tasks

Goal: every action item the LLM extracts can be converted to a real Zero task with one click, optionally auto.

Backend ([backend/app/routers/meetings.py](backend/app/routers/meetings.py)):
1. New `POST /api/meetings/{id}/action-items/create-tasks` (body `{owner_filter: "all" | "me", auto_assign: bool}`). Walks `summary.action_items`, calls existing task service (search `app/services/` for the canonical task creator — likely `TaskService.create_task()`), tags task with `meeting_id`, sets `description` = action_item.description, `due_date` = action_item.due (parse ISO best-effort), assignee = primary user when owner matches "me" / primary voiceprint display_name.
2. New `GET /api/meetings/{id}/action-items` returning the structured list with task linkage status.

Settings: new env var `ZERO_AUTO_CREATE_TASKS_FROM_MEETINGS` (default `false`); when true the pipeline calls the create-tasks endpoint after summary completes with `owner_filter="me"`.

Frontend ([frontend/src/components/reachy/LiveMeetingPanel.tsx](frontend/src/components/reachy/LiveMeetingPanel.tsx)):
1. After summary loads, render each action item with a "Create task" button (or batch "Create all my tasks").
2. After creation: action item shows a green "→ Task #123" link (deep-link to existing task page).
3. Setting toggle in [ReachyVoiceSettingsPage.tsx](frontend/src/pages/ReachyVoiceSettingsPage.tsx) → "Auto-create tasks for action items assigned to me" (writes to backend setting).

## Phase 4 — Live running notes during recording

Goal: live "running summary + action items so far" sidebar that updates every 60 sec while recording.

Backend:
1. New scheduler-style coroutine kicked off in `meeting_recording_service.start_recording()`: every 60 sec, pull last 60 sec of `liveSegments`, call a lightweight `meeting_summary_service.live_summary(buffer)` that prompts a small LLM (route `kimi-k2.5-light` via `UnifiedLLMClient` with `temperature=1`) for `{running_notes_delta, new_action_items}`. Push via the existing `meeting_processing` WS as `{stage: "live_notes", payload: {...}}`.
2. Stop the coroutine on `stop_recording()`.

Frontend ([frontend/src/components/reachy/LiveMeetingPanel.tsx](frontend/src/components/reachy/LiveMeetingPanel.tsx)):
1. While `phase === 'recording'`, render a 2-column layout: left = live transcript (existing), right = "Running notes" with bullet list of accumulated running_notes_delta + a tally of detected action items.
2. Reachy speaks (`reachy.say`) at minute 5/10/15: "5 minutes in, 2 action items captured." Throttled by elapsed time.

## Phase 5 — ReachyMeetingsPage UX polish

Goal: even when calendar is connected, the page should feel rich.

Changes in [frontend/src/pages/ReachyMeetingsPage.tsx](frontend/src/pages/ReachyMeetingsPage.tsx):
1. Top header strip: 4 stat cards — "Connected: <email>", "Synced <Xm ago>", "Auto-record: ON/OFF", "Voice enrolled: yes/no" with quick actions on click.
2. After the upcoming-events list, add **Recent meetings** (already in Phase 0) with summary preview, action-item count badge, "Open" button.
3. Add **Search past meetings** input that calls `GET /api/meeting-search/?q=...` (already exists, see [meeting_search.py](backend/app/routers/meeting_search.py)) and renders inline results.
4. Reachy voice cues on auto-record start ("Recording your meeting with <attendee>") and on summary ready ("Summary ready, N action items").

## Phase 6 — Auto-record-everything master switch

Goal: one toggle that turns on auto-record for every newly-synced calendar event that has attendees (i.e. real meetings, not blockers).

Backend:
1. New env-backed user setting `ZERO_AUTO_RECORD_ALL` (boolean), exposed via `GET/PATCH /api/settings/auto-record-all`.
2. After each `calendar_check` scheduler run that pulls new events, if the setting is ON: for every newly-cached event with `has_attendees=true` and not already linked to a meeting, call the existing `from-event` flow + flip `auto_record_enabled=true`.

Frontend: a single toggle in the ReachyMeetingsPage header (next to "Sync now"). On enable, show a confirmation dialog warning that all attendee meetings will record automatically.

## Verification

End-to-end smoke test once all phases land:

1. **Phase 0 visibility**: open `http://localhost:5173/reachy/meetings` with calendar disconnected → CTA shown. Click → OAuth flow → events appear within 10 sec (auto-sync). Recent meetings strip renders below.
2. **Phase 1 enrollment**: open `/reachy/voice` → click "Enroll yourself" → speak for 30 sec → `GET /api/voiceprints` shows 1 row with `is_primary=true`.
3. **Phase 1 recognition**: start a meeting via `QuickMeetingDialog`, talk for 60 sec, stop. After processing completes, the transcript segments display "Me" instead of "SPEAKER_00" for your voice.
4. **Phase 2 memory**: in MeetingDetailPage manually relabel `SPEAKER_01 → "Bob"`. Start a new meeting where Bob talks — segments show "Bob" automatically.
5. **Phase 3 tasks**: end a meeting whose summary contains action items. Click "Create all my tasks". Check `/sprints` → tasks appear, deep-linked back to the meeting.
6. **Phase 4 live notes**: while recording, Running Notes sidebar updates every 60 sec; `LiveMeetingPanel` shows growing bullets.
7. **Phase 5 stats**: header shows 4 stat cards. Search input returns hits from past meetings.
8. **Phase 6 auto-record-all**: toggle ON → next calendar sync → all attendee events get `auto_record=true` (visible green badge in MeetingCard).

Commands:
```bash
# Backend rebuild after changes (CLAUDE.md mandate)
docker compose -f docker-compose.sprint.yml build --no-cache zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api

# Frontend rebuild for new hooks/components (volume-mounted but new packages need rebuild — pgvector adapter may add a python dep; no JS dep changes expected)
docker compose -f docker-compose.sprint.yml restart zero-ui

# Host agent reload (after voice-enrollment endpoint added)
# auto-restart.bat watches uvicorn — touching host_agent/main.py triggers reload via Scheduled Task

# Check health
curl http://localhost:18792/api/calendar/status
curl http://localhost:18794/health
curl http://localhost:18792/api/voiceprints
```

## Out of scope

- Replacing pyannote with WhisperX/NeMo. Pyannote already works and the embedding API is good enough for personal voiceprints.
- Resurrecting the orphaned `C:\code\DailyMeetings` standalone app — it's superseded by the host_agent + zero-api flow.
- Multi-user voiceprint enrollment over the network (only the local primary user matters here).
