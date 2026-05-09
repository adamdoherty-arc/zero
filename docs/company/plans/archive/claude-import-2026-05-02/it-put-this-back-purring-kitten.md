# Reachy Meetings + Meeting Mode — Fix & E2E Test

## Context

Three issues surfaced on the Reachy pages:

1. **Sidebar highlight bug** — Clicking "Reachy Meetings" also highlights "Reachy" in [frontend/src/components/layout/AppSidebar.tsx](frontend/src/components/layout/AppSidebar.tsx). Both items render as active because the `isActive` check uses prefix matching, and `/reachy/meetings` starts with `/reachy`.
2. **Meeting mode "doesn't work"** — The "Start meeting mode" button on the Reachy Motion Library page ([ReachyMotionLibraryPage.tsx:476-481](frontend/src/pages/ReachyMotionLibraryPage.tsx#L476-L481)) fires a mutation with no visible feedback. The code path is correct (POST `/api/reachy/presence/meeting/start` → `reachy_presence_service.start_meeting_mode()` → DoA loop), but there's no success toast and no indication it ran. If the `/api/state/doa` endpoint on the daemon fails, the loop silently continues — the user sees nothing.
3. **Quick meeting / E2E test** — `AddEventDialog` only creates *Google Calendar* events, which requires OAuth and the scheduled time to hit before recording makes sense. There's no "record a meeting right now" path from the UI. Also need to verify the full pipeline works: record → transcribe → summarize.

## Critical files

### Fix 1 — Sidebar
- [frontend/src/components/layout/AppSidebar.tsx:141-144](frontend/src/components/layout/AppSidebar.tsx#L141-L144) — `isActive()` uses `startsWith()`.

### Fix 2 — Meeting mode feedback
- [frontend/src/pages/ReachyMotionLibraryPage.tsx:466-481](frontend/src/pages/ReachyMotionLibraryPage.tsx#L466-L481) — Start/Stop meeting buttons.
- [frontend/src/hooks/useReachyApi.ts:394-420](frontend/src/hooks/useReachyApi.ts#L394-L420) — `useMeetingState`, `useStartMeetingMode`, `useStopMeetingMode`.
- [backend/app/services/reachy_presence_service.py:272-355](backend/app/services/reachy_presence_service.py#L272-L355) — service logic; DoA loop swallows exceptions.
- [backend/app/services/reachy_service.py:206-208](backend/app/services/reachy_service.py#L206-L208) — `get_doa()` calls daemon `/api/state/doa`.

### Fix 3 — Quick meeting
- [frontend/src/pages/ReachyMeetingsPage.tsx](frontend/src/pages/ReachyMeetingsPage.tsx) — page to host a new button.
- [frontend/src/components/reachy/AddEventDialog.tsx](frontend/src/components/reachy/AddEventDialog.tsx) — pattern to mirror for a new "Quick meeting" dialog.
- [backend/app/routers/meetings.py:62-76](backend/app/routers/meetings.py#L62-L76) — `POST /api/meetings/` already supports ad-hoc creation (no calendar event required).
- [backend/app/routers/meetings.py:123-139](backend/app/routers/meetings.py#L123-L139) — `POST /api/meetings/{id}/record-now`.
- [frontend/nginx.conf:46-141](frontend/nginx.conf#L46-L141) — proxies `/api/meeting-recordings/*`, `/api/meeting-transcriptions/*`, `/api/meeting-summaries/*` to DailyMeetings on `host.docker.internal:18793`.
- DailyMeetings routers at `C:\code\DailyMeetings\app\routers\{meeting_recordings,meeting_transcriptions,meeting_summaries}.py` — already implement stop, retranscribe, generate.

## Plan

### 1. Sidebar exact-match fix

In [AppSidebar.tsx:141-144](frontend/src/components/layout/AppSidebar.tsx#L141-L144), replace the `isActive` function:

```tsx
const isActive = (href: string) => {
  if (href === '/') return location.pathname === '/'
  // Exact match, or a descendant path (e.g. /reachy/some-sub-view).
  // Guard against false positives: any nav item whose href is a strict
  // prefix of the current pathname loses to the more-specific nav item.
  if (location.pathname === href) return true
  if (!location.pathname.startsWith(href + '/')) return false
  // Lose to any more-specific nav item in the sidebar.
  const moreSpecific = NAV_GROUPS.flatMap((g) => g.items)
    .map((i) => i.href)
    .some((h) => h !== href && h.startsWith(href + '/') && (location.pathname === h || location.pathname.startsWith(h + '/')))
  return !moreSpecific
}
```

Rationale: `/reachy/meetings` is an exact match for its own item, and the "Reachy" item at `/reachy` now loses because a more-specific item (`/reachy/meetings`) matches. Works without listing special cases. `NAV_GROUPS` is already in module scope above.

### 2. Meeting mode — visible feedback + resilient loop

**Frontend** — mirror the pomodoro pattern so the user gets a toast, and show an error if the mutation fails:

In [ReachyMotionLibraryPage.tsx:476-481](frontend/src/pages/ReachyMotionLibraryPage.tsx#L476-L481), wrap the start handler:
```tsx
onClick={async () => {
  try { await startMeeting.mutateAsync(undefined); toast({ title: 'Meeting mode on' }) }
  catch (e) { toast({ title: 'Start failed', description: String(e), variant: 'destructive' }) }
}}
```
Same shape for the stop button (line 466-471): toast on success, toast on failure.

Also add a small "DoA unavailable" note inside the active block if `meeting.data?.doa_available === false` (new optional field — see backend change below) so the user understands when the daemon isn't returning DoA but the mode is still "on".

**Backend** — surface DoA health in the state endpoint so the frontend can warn instead of silently looking normal:

In [reachy_presence_service.py](backend/app/services/reachy_presence_service.py), in `meeting_state()` return payload, include a `doa_available` boolean that reflects whether the last DoA probe succeeded. Set it inside `_meeting_loop` after each `svc.get_doa()` call (true on success, false on any exception). Default false when meeting isn't active.

No router change needed; the response is already a plain dict.

### 3. Quick meeting + inline live panel (E2E transcription/summary)

User chose: new "Quick meeting" button next to "Add event", with an inline live-transcript panel below the header on the same page — no new route.

**New component** — `frontend/src/components/reachy/QuickMeetingDialog.tsx`, modeled on `AddEventDialog`:
- Fields: title (required), duration minutes (default 5, min 1, max 120).
- On submit:
  1. `POST /api/meetings/` with `{ title, start_time: now, end_time: now + duration_minutes, participants: [] }` → `{ id }`.
  2. `POST /api/meetings/{id}/record-now`.
  3. Closes dialog and sets an `activeQuickMeetingId` piece of state on `ReachyMeetingsPage` via a callback.

**New component** — `frontend/src/components/reachy/LiveMeetingPanel.tsx`, inline. Renders only when `activeQuickMeetingId` is set:
- Subscribes to `ws://<host>/ws/meeting-live-transcript?meeting_id=<id>` (proxied via [nginx.conf](frontend/nginx.conf)) through a new `useLiveTranscript(meetingId)` hook, collecting segments into a scrollable list.
- Shows elapsed time + a red "Stop & summarise" button.
- On stop click, uses a new `useQuickMeetingLifecycle()` hook that sequentially:
  1. `POST /api/meeting-recordings/stop` with `{ meeting_id }`.
  2. Transitions UI to "Transcribing…"; `POST /api/meeting-transcriptions/{id}/retranscribe`; polls `GET /api/meeting-transcriptions/{id}` until `status === "done"`.
  3. Transitions UI to "Summarising…"; `POST /api/meeting-summaries/{id}/generate`; polls `GET /api/meeting-summaries/{id}` until ready.
  4. Displays the summary inline (markdown) with links to the recording + full transcript.

**Page integration** — [ReachyMeetingsPage.tsx:100](frontend/src/pages/ReachyMeetingsPage.tsx#L100):
- Add `<QuickMeetingDialog onStarted={setActiveQuickMeetingId} />` next to `<AddEventDialog />`.
- Render `{activeQuickMeetingId && <LiveMeetingPanel meetingId={activeQuickMeetingId} onDone={() => setActiveQuickMeetingId(null)} />}` below the header div.
- Button disabled when DailyMeetings health is `!ok` (see section 4).

**Existing reuse**:
- `POST /api/meetings/` already supports ad-hoc creation with no calendar event — [meetings.py:62-76](backend/app/routers/meetings.py#L62-L76).
- DailyMeetings endpoints for stop / retranscribe / generate already exist and are proxied.
- No backend router additions required beyond the DoA flag (section 2) and the health proxy (section 4).

## 4. DailyMeetings bring-up + health banner

User wants me to start DailyMeetings as part of this work and wire helpful integration.

**Bring-up** (as part of the execution, before testing):
```
cd C:\code\DailyMeetings
# If venv missing: python -m venv venv && venv\Scripts\pip install -r requirements.txt
venv\Scripts\python run.py
```
Leave running in background and verify `curl http://localhost:18793/health` returns 200.

**New backend endpoint** — `GET /api/meetings/dailymeetings-health` in [backend/app/routers/meetings.py](backend/app/routers/meetings.py):
- Proxies to `http://host.docker.internal:18793/health` with 1s timeout.
- Returns `{ ok: bool, version?: str, message?: str }`.
- No auth change; uses existing router dependencies.

**New frontend hook** — `useDailyMeetingsHealth()` in `hooks/useMeetings.ts`, polls that endpoint every 30s.

**Banner** on [ReachyMeetingsPage.tsx](frontend/src/pages/ReachyMeetingsPage.tsx) (above the events list): if `!ok`, render an amber warning card with the exact command to start DailyMeetings and a "Retry" button. Quick-meeting button is disabled while `!ok`, with tooltip explaining why. This mirrors the existing host_agent warning on the Motion Library page for consistency.

## Prerequisites

- **Reachy daemon** at `:8000` — running (pid 51056 per current UI).
- **host_agent at :18794** — not required for the quick-meeting path (meetings router falls back to in-process `start_recording` when `ZERO_HOST_AGENT_URL` is unset, see [meetings.py:129-132](backend/app/routers/meetings.py#L129-L132)). It *is* required for Reachy's DoA microphone array (Meeting Mode) — UI already warns about this.
- **DailyMeetings :18793** — I will start it.

## Verification

1. **Sidebar**: visit `/reachy/meetings` — only "Reachy Meetings" highlighted. Visit `/reachy` — only "Reachy" highlighted. Visit `/reachy/teleop` and `/reachy/home-assistant` — each highlights exactly one item.
2. **Meeting mode**: click "Start meeting mode". Toast "Meeting mode on" appears. Card flips to "Looking at speaker" within 2s. Click "Exit meeting". Toast "Meeting mode off". Card returns to idle. If Reachy daemon `/api/state/doa` 404s, card shows "DoA unavailable" badge but mode still toggles.
3. **DailyMeetings bring-up**: `curl http://localhost:18793/health` returns 200. `GET /api/meetings/dailymeetings-health` through Zero returns `{ ok: true }`. Reachy Meetings page banner is absent.
4. **Quick meeting E2E**:
   - Click "Quick meeting" on `/reachy/meetings`. Title "Zero test meeting", duration 2 min. Submit.
   - Dialog closes; live panel appears below header showing "Recording…" and elapsed timer.
   - Speak into mic for ~30s; transcript segments stream into the panel.
   - Click "Stop & summarise". UI transitions: Recording → Transcribing → Summarising → Done.
   - Final summary renders inline.
   - DB check via `docker exec zero-db psql -U postgres -d zero -c "SELECT id, title FROM meetings ORDER BY created_at DESC LIMIT 1;"` returns the new meeting. `meeting_recordings`, `meeting_transcriptions`, `meeting_summaries` all have rows linked to that id.
5. **No regressions**: Pomodoro panel still works; "Record now" and "Auto-record" on existing calendar-based meeting cards still work; "Add event" (Google Calendar) still works.

## Deployment

Backend change (meeting_state payload): rebuild `zero-api`:
```
docker compose -f docker-compose.sprint.yml build --no-cache zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api
```
Frontend changes: source is volume-mounted, no rebuild needed. Verify with `docker logs -f zero-ui` for Vite HMR.
