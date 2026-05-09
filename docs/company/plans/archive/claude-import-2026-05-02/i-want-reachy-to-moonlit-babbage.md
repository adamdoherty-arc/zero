# Reachy: Meeting Prep + Email Voice Triage

**Filed via**: `/zero-reachy-audit --ask` (will become `REQ-NNN` in `REQUESTS_LOG.md`)
**Dimensions touched**: Meeting Mode, Voice & Conversation, Presence & Ambient, Persona & Emotion

---

## Context

User wants Reachy to handle two related "executive assistant" loops:

1. **Meeting prep**: Pull from Google Calendar so the user can see upcoming meetings on a Reachy page, add events, and have Reachy auto-prepare to record. Today there's no Reachy calendar UI; calendar nudges run as voice-only announcements every minute.
2. **Email triage by voice**: When a new email arrives, Reachy announces it ("you have a new email from X about Y, read or ignore?"). On "read", Reachy reads the body **in a different voice**. Voice commands `delete` and `respond` should also work end-to-end.

The whole stack is mostly already there — calendar sync, meeting recording pipeline, email polling, voice loop, persona system, TTS with two engines, and proactive scheduler nudges all exist. The new work is (a) a Reachy frontend page for meetings, (b) auto-record-at-start hookup, (c) a multi-turn email voice state machine, (d) per-utterance TTS voice override, (e) Gmail send + trash actions that don't exist yet.

---

## What Already Works (Reuse As-Is)

| Capability | Source | How we use it |
|---|---|---|
| Google Calendar OAuth + sync + list/create | [backend/app/services/calendar_service.py](backend/app/services/calendar_service.py) | Power the Reachy calendar page |
| Calendar nudge (5/1 min) | [scheduler_service.py:1396-1468](backend/app/services/scheduler_service.py#L1396-L1468) | Extend with "starting now → record" branch |
| Meeting recording start/stop | [meeting_recording_service.py:56-181](backend/app/services/meeting_recording_service.py#L56-L181) | Trigger from auto-recorder + UI button |
| `MeetingModel.calendar_event_id` FK | [backend/app/db/models.py](backend/app/db/models.py) | Link a recording to its calendar event — no schema change |
| Reachy mic auto-detect | [meeting_audio_capture.py:122-145](backend/app/services/meeting_audio_capture.py#L122-L145) | Already prefers Reachy USB mic |
| Gmail incremental sync | [gmail_service.py:662-774](backend/app/services/gmail_service.py#L662-L774) | Poll cadence stays at 5 min for MVP |
| Email mark-read + archive | [gmail_service.py:511-567](backend/app/services/gmail_service.py#L511-L567) | "Ignore" → archive; "delete" needs new method |
| Email draft generator | [email_draft_service.py:17-80](backend/app/services/email_draft_service.py#L17-L80) | Power "respond" flow; needs send hookup |
| Reachy voice loop (STT→LLM→TTS) | [voice_loop_service.py:33-282](backend/app/services/voice_loop_service.py#L33-L282) | Power email triage follow-ups |
| TTS dual-engine (piper + edge-tts) | [tts_service.py:23-186](backend/app/services/tts_service.py#L23-L186) | Add `voice_override` param for "different voice" |
| Push-to-Reachy (`reachy.say`, `play_emotion`) | [reachy_service.py:477-510](backend/app/services/reachy_service.py#L477-L510) | Announcement layer |
| Email nudge job | [scheduler_service.py:1470-1510](backend/app/services/scheduler_service.py#L1470-L1510) | Replace count-based prompt with per-email triage |
| MCP tool `get_calendar_events` | [mcp_servers/zero_api_mcp.py:148-156](mcp_servers/zero_api_mcp.py#L148-L156) | Already exposed for Claude |

---

## What's Missing (Must Build)

| Gap | Severity | Approach |
|---|---|---|
| Reachy frontend "Meetings" page | UI | New page reusing existing calendar + meeting hooks |
| "Record this meeting" button per event | UI | New hook + endpoint that links a recording to a calendar event |
| Auto-record at meeting start (opt-in) | Backend | New scheduler branch in `_run_reachy_calendar_nudge` (it already runs every minute) |
| Multi-turn email triage state machine | Backend | New `email_voice_session_service.py` — finite state, in-memory dict, 60s timeout |
| Per-utterance TTS voice override | Backend | Add `voice_override: str \| None` param to `tts_service.synthesize` and `reachy.say` |
| Gmail send (reply) | Backend | New method on `gmail_service.send_email(to, subject, body, in_reply_to)` — `gmail.modify` scope already covers it |
| Gmail trash (vs archive) | Backend | New `gmail_service.trash_email(id)` — adds TRASH label |
| Voice intent routing for {read, ignore, delete, respond} | Backend | LLM classifier with strict JSON output + keyword fast-path |
| Push-to-Reachy that **expects a reply** | Backend | Extend `reachy.say` with optional `await_reply: bool` that arms the wake-word/STT short-window |

---

## Workstream A — Meeting Prep on Reachy

### Scope
- New Reachy page that shows upcoming meetings (today + 7 days) pulled from Google Calendar.
- "Add event" form that creates calendar events.
- Per-event "Record this meeting" button → creates `MeetingModel` linked to the event, ready to start when meeting begins.
- Optional per-event "Auto-record" toggle — when enabled, Reachy starts recording automatically at event start time and stops at end time.

### Files to create
- [frontend/src/pages/ReachyMeetingsPage.tsx](frontend/src/pages/ReachyMeetingsPage.tsx) — list view, day grouping, status badges (upcoming / recording / completed), quick "Record" / "Auto-record" toggle.
- [frontend/src/components/reachy/MeetingCard.tsx](frontend/src/components/reachy/MeetingCard.tsx) — single-event card with title, time, attendees, action buttons.
- [frontend/src/components/reachy/AddEventDialog.tsx](frontend/src/components/reachy/AddEventDialog.tsx) — minimal form (title, start, end, attendees).
- [frontend/src/hooks/useCalendarApi.ts](frontend/src/hooks/useCalendarApi.ts) — React Query hooks: `useCalendarEvents`, `useCreateEvent`, `useScheduleRecording`, `useToggleAutoRecord`. Use existing `/api/calendar/*` routes; only add hooks, not new routes for read paths.
- [backend/app/services/meeting_auto_recorder_service.py](backend/app/services/meeting_auto_recorder_service.py) — small service with `mark_for_auto_record(event_id)`, `unmark`, `due_recordings(now)`. Persists to a new `MeetingAutoRecordModel` table or to a JSON file at `workspace/meetings/auto_record.json` (prefer JSON for MVP — no migration needed).

### Files to modify
- [backend/app/services/scheduler_service.py](backend/app/services/scheduler_service.py) — extend `_run_reachy_calendar_nudge` (line 1396): on the bucket where event is starting `now ± 30s`, if event_id is marked for auto-record, call `meeting_recording_service.start_recording(meeting_id=...)`. Stop trigger handled by another minute-tick that compares `now` against `end_time`.
- [backend/app/routers/meetings.py](backend/app/routers/meetings.py) — add `POST /api/meetings/from-event` (creates `MeetingModel` linked to a `calendar_event_id`, returns id), `POST /api/meetings/{id}/auto-record` (toggle), `POST /api/meetings/{id}/record-now` (immediate start).
- [frontend/src/App.tsx](frontend/src/App.tsx) — add `/reachy/meetings` route.
- Sidebar config (find via grep for `ReachyMotionLibraryPage` import) — add "Meetings" entry.

### Verification (Workstream A)
1. `docker compose -f docker-compose.sprint.yml build --no-cache zero-api && up -d zero-api` — backend rebuild after service + router changes.
2. Frontend is volume-mounted; just `restart zero-ui`.
3. Open `/reachy/meetings` — confirm the list renders today's calendar events.
4. Create an event for 2 minutes in the future via the "Add Event" dialog. Toggle auto-record. Wait 2 minutes. Verify:
   - `docker logs zero-api | grep -E "reachy_calendar_nudge|recording_started"` shows the nudge fires and recording starts.
   - `MeetingRecordingModel` row exists with `calendar_event_id` set.
   - Reachy speaks "Recording started." (already wired in `meeting_recording_service.py:116-122`).
5. End the event time → recording stops automatically, processing pipeline kicks off, transcript appears in `/meetings/{id}` page.

---

## Workstream B — Email Voice Triage Loop

### Scope
- When new email(s) arrive (per 5-min sync), Reachy announces **per email** (not just unread count): "You have a new email from {sender}: {subject}. Read or ignore?"
- Multi-turn state machine: `prompted → awaiting_decision → reading | ignored | deleting | responding → idle`.
- Email body read **in a different voice** than the announcement voice.
- "Respond" → voice transcription of user's intent → LLM-drafted reply → Reachy reads draft back → user confirms `send` or `cancel`.
- "Delete" → Gmail TRASH (recoverable for 30 days, matches user mental model of delete).

### Files to create
- [backend/app/services/email_voice_session_service.py](backend/app/services/email_voice_session_service.py) — finite state machine. In-memory dict keyed by session_id (only one active session at a time anyway). States: `idle`, `awaiting_decision`, `reading`, `awaiting_post_read_action`, `composing_reply`, `awaiting_send_confirmation`. 60s timeout per state → revert to idle. Owns the email queue (FIFO of unread email_ids that arrived but haven't been triaged).
- [backend/app/services/voice_intent_router.py](backend/app/services/voice_intent_router.py) — small classifier. Fast path: keyword match on {`read`, `yes`, `go ahead`, `ignore`, `skip`, `no`, `delete`, `trash`, `respond`, `reply`, `send`, `cancel`, `stop`}. Slow path: LLM classifier with strict JSON output for ambiguous input. Returns `intent: Literal[...]` + confidence.
- [backend/app/routers/reachy_email.py](backend/app/routers/reachy_email.py) — endpoints:
  - `POST /api/reachy/email/voice-input` — accepts WAV, transcribes, routes intent through session, returns next prompt + actions taken.
  - `GET /api/reachy/email/session` — current session state (for UI debug panel).
  - `POST /api/reachy/email/skip` — manual "skip current email" hook for UI fallback.

### Files to modify
- [backend/app/services/tts_service.py](backend/app/services/tts_service.py) — add `voice_override: str | None = None` param to `synthesize`. When set, use edge-tts (cheap path) with that voice regardless of primary engine. Fall back to default voice if edge-tts unavailable.
- [backend/app/services/reachy_service.py](backend/app/services/reachy_service.py) — `say()` gains optional `voice_override` param, passed straight to `tts_service.synthesize`. No daemon-side changes.
- [backend/app/services/gmail_service.py](backend/app/services/gmail_service.py) — add:
  - `async def send_email(self, to: str, subject: str, body_text: str, in_reply_to: str | None = None) -> str` — uses Gmail API `users.messages.send` with RFC 2822 encoded message; sets `In-Reply-To` and `References` headers when replying.
  - `async def trash_email(self, email_id: str) -> bool` — adds TRASH label, removes INBOX, updates DB row to `status=trashed`.
  - Need to verify `gmail.modify` scope covers send. If not, add `gmail.send` to `GOOGLE_SCOPES` and force re-auth (one-time user action — flag this in the verification step).
- [backend/app/services/scheduler_service.py](backend/app/services/scheduler_service.py) — replace `_run_reachy_email_nudge` body. New behavior: pull unread emails arrived since `last_check`, push each into `email_voice_session_service.enqueue(email_id)`. If session is idle, fire the first prompt via `reachy.say` and arm the wake-word for a follow-up reply.
- [backend/app/services/voice_loop_service.py](backend/app/services/voice_loop_service.py) — small change: when an email session is active (check `email_voice_session_service.is_active()`), route the transcribed text to `voice_intent_router` first; if it returns an email-domain intent with confidence ≥ 0.7, hand it to the session and skip the LLM chat. Otherwise treat as normal voice input.

### Voice configuration (the "different voice" decision)

Default voice (announcement): existing `TTS_EDGE_VOICE` (`en-US-AriaNeural`).
Email-reading voice: hard-coded `en-GB-RyanNeural` for MVP — distinct gender + accent so the user can hear the switch. Make it overridable via `ZERO_REACHY_EMAIL_READER_VOICE` env var.

Rationale: edge-tts supports ~50 voices and switching is per-call, no model loading. Building a full per-persona voice config (touched in the audit) is a separate `INTEGRATION_IDEAS.md` follow-up; this plan ships the simpler version.

### State machine (text form)

```
[IDLE]
  ↓ scheduler enqueues email, session.start()
  ↓ reachy.say("New email from {sender}: {subject}. Read or ignore?")
[AWAITING_DECISION]  (60s timeout → IDLE, leaves email unread)
  ├─ intent=read → reachy.say(body_summary, voice_override=READER) → [AWAITING_POST_READ_ACTION]
  ├─ intent=ignore → gmail.archive_email() → next email or [IDLE]
  ├─ intent=delete → gmail.trash_email() → next email or [IDLE]
  └─ intent=respond → [COMPOSING_REPLY]
[AWAITING_POST_READ_ACTION]  ("delete, respond, or next?")
  ├─ intent=delete → trash → next or [IDLE]
  ├─ intent=respond → [COMPOSING_REPLY]
  └─ intent=skip/next → next or [IDLE]
[COMPOSING_REPLY]  ("What would you like to say?")
  ↓ user speaks → STT → email_draft_service.draft_reply(intent_text=...)
  ↓ reachy.say(f"I'd send: {draft}. Say send or cancel.", voice_override=READER)
[AWAITING_SEND_CONFIRMATION]
  ├─ intent=send → gmail.send_email() → reachy.say("Sent.") → next or [IDLE]
  └─ intent=cancel → reachy.say("Cancelled.") → next or [IDLE]
```

### Verification (Workstream B)
1. Backend rebuild required (new services, router, gmail methods).
2. Re-auth Gmail at `http://localhost:18792/api/google/auth/url` if `gmail.send` scope was added (check first — `gmail.modify` may already cover it).
3. Send yourself a test email. Within ≤ 5 min Reachy announces it in default voice.
4. Say "read" → confirm Reachy reads body in `en-GB-RyanNeural` (audibly different).
5. Say "delete" → confirm email moves to Trash in Gmail web (not just archive).
6. Send another test → say "respond" → speak a one-line intent → confirm Reachy reads back the draft → say "send" → confirm reply lands in your sent folder with correct `In-Reply-To` header.
7. Test timeout: announce a new email, stay silent 70s → confirm session reverts to idle without taking action.
8. Test interruption: during reading, say "stop" → confirm Reachy stops mid-sentence (handle in session — set state to `IDLE`, call `reachy.stop_sound`).

---

## Confirmed Decisions

1. **"Different voice"** = edge-tts voice swap (`en-GB-RyanNeural`), overridable via `ZERO_REACHY_EMAIL_READER_VOICE`. Per-persona voice mapping is a follow-up `INTEGRATION_IDEAS.md` entry.
2. **"Delete"** = Gmail Trash (TRASH label, removes INBOX). Recoverable for 30 days. **[Confirmed]**
3. **"Respond"** = confirm-then-send. User speaks intent → LLM draft → Reachy reads draft in reader voice → user says `send` or `cancel`. **[Confirmed]**
4. **Real-time email arrival** = current 5-min poll. Webhook upgrade is a follow-up.
5. **Auto-record meetings** = opt-in per event via per-card toggle.
6. **Email-voice session state** = in-memory dict in `email_voice_session_service` (single-user, single Reachy).
7. **Phasing** = **both workstreams built in parallel** (user decision). Atomic commits per slice so either can land independently if the other stalls.

---

## Build Order (Both Workstreams in Parallel)

The two workstreams touch mostly disjoint files, so they can advance side by side. The shared touch points (`scheduler_service.py`, sidebar nav) get atomic commits to avoid merge friction.

**Slice 1 — Foundation (can run simultaneously)**
- A1: Backend endpoints `POST /api/meetings/from-event`, `POST /api/meetings/{id}/record-now`, `POST /api/meetings/{id}/auto-record` in [meetings.py](backend/app/routers/meetings.py).
- B1: TTS `voice_override` param + `reachy.say` passthrough. Smallest possible diff in [tts_service.py](backend/app/services/tts_service.py) and [reachy_service.py](backend/app/services/reachy_service.py).
- B2: Verify `gmail.modify` covers send (one Gmail API test call). If yes, no scope change. If no, add `gmail.send` to `GOOGLE_SCOPES` and surface the re-auth requirement.

**Slice 2 — Core capability**
- A2: `meeting_auto_recorder_service.py` (JSON-backed, no migration) + scheduler branch in `_run_reachy_calendar_nudge` for auto-start at event time.
- A3: Auto-stop minute-tick — separate scheduler job `reachy_meeting_auto_stop` that compares `now` vs `end_time` for active recordings flagged auto-record.
- B3: `gmail_service.send_email()` and `trash_email()`.
- B4: `voice_intent_router.py` (keyword fast path + LLM fallback).
- B5: `email_voice_session_service.py` state machine.

**Slice 3 — Glue + UI**
- A4: Frontend `useCalendarApi.ts` hooks + `ReachyMeetingsPage.tsx` + `MeetingCard.tsx` + `AddEventDialog.tsx`.
- A5: Sidebar entry + route in `App.tsx`.
- B6: `routers/reachy_email.py` endpoints.
- B7: `voice_loop_service.py` modification to route through `voice_intent_router` when an email session is active.
- B8: Replace `_run_reachy_email_nudge` body to enqueue per-email instead of broadcasting count.

**Post-MVP follow-ups (file in `INTEGRATION_IDEAS.md` as hot)**
- Per-persona voice config (`persona_voice_config.json`).
- Gmail Pub/Sub webhook for sub-second email arrival.
- Auto-record-all toggle with quiet-hours respect.
- "Reply with persona" — let user say "respond as a Victorian butler" and have draft + voice match.

---

## Audit Skill Bookkeeping

When this work ships, the audit skill needs:
- `REQUESTS_LOG.md` entry transitions: `pending → researched (this plan) → planned → integrated → verified`.
- `MASTER_SCORECARD.md` should reflect uplift on Meeting Mode and Voice & Conversation dimensions on the next audit run.
- `LEARNINGS.md` entry: any patterns observed during build (e.g., scope-add gotcha for Gmail send, edge-tts voice latency).
- Add to `INTEGRATION_IDEAS.md` (hot): per-persona voice config, Pub/Sub webhook, "respond as persona".

---

## Critical Files Reference

**Backend (modify)**
- [backend/app/services/scheduler_service.py:1396-1510](backend/app/services/scheduler_service.py#L1396-L1510) — calendar + email nudge jobs
- [backend/app/services/voice_loop_service.py:33-282](backend/app/services/voice_loop_service.py#L33-L282) — route to email session when active
- [backend/app/services/tts_service.py:74-93](backend/app/services/tts_service.py#L74-L93) — add `voice_override` param
- [backend/app/services/reachy_service.py:477-510](backend/app/services/reachy_service.py#L477-L510) — pass through `voice_override`
- [backend/app/services/gmail_service.py:511-567](backend/app/services/gmail_service.py#L511-L567) — add `send_email`, `trash_email`
- [backend/app/services/gmail_oauth_service.py:20-28](backend/app/services/gmail_oauth_service.py#L20-L28) — verify scope for send
- [backend/app/routers/meetings.py](backend/app/routers/meetings.py) — add from-event, record-now, auto-record endpoints

**Backend (create)**
- `backend/app/services/email_voice_session_service.py`
- `backend/app/services/voice_intent_router.py`
- `backend/app/services/meeting_auto_recorder_service.py`
- `backend/app/routers/reachy_email.py`

**Frontend (create)**
- `frontend/src/pages/ReachyMeetingsPage.tsx`
- `frontend/src/components/reachy/MeetingCard.tsx`
- `frontend/src/components/reachy/AddEventDialog.tsx`
- `frontend/src/hooks/useCalendarApi.ts`

**Frontend (modify)**
- [frontend/src/App.tsx](frontend/src/App.tsx) — add route
- Sidebar nav config — add entry
