# Reachy Capability Requests Log

User-filed "I want Reachy to do X" items. Each entry has a lifecycle: `pending` → `researched` → `planned` → `integrated` → `verified`. Archive rows move to `history/requests_archive.md` after 30 days in `verified`.

## Open requests

### REQ-003: Stop uncontrolled body shaking and make companion body motion opt-in
- **Filed**: 2026-05-05
- **Raw ask**: "The robot is just shaking uncontrollable now, why does this keep happening?"
- **State**: `integrated-awaiting-physical-verify`
- **Dimensions**: 1 (Motion & Body), 2 (Voice & Conversation), 4 (Presence & Ambient), 6 (Environment & Integrations)
- **Root cause**: Assistant activation and legacy surfaces could still start the daemon/watchdog, enable motors, play motions, or run background motion despite the companion policy defaulting `body_motion_enabled=false`.
- **Integrated fixes**:
  - `reachy_motion_policy.py` fail-closed gate.
  - Voice-only assistant activation defaults; daemon/watchdog/motors stay off unless explicitly requested and policy allows.
  - Motion guard coverage across direct routes, realtime tools/session, classic voice gestures, HA watcher, presence, sequence playback, move recorder/replay, and radio.
  - Recorded move stop now disables motors instead of re-enabling torque.
- **Verification complete**:
  - [x] Backend unit coverage for companion policy lock.
  - [x] Assistant tests updated to safer default behavior.
  - [x] Safety routes/services compile.
  - [x] `zero-api` deployed after safety patch.
- **Verification still blocked by hardware**:
  - [ ] Confirm physical robot remains still after assistant activation.
  - [ ] Confirm explicit body-motion opt-in only works after serial/motor stability is resolved.
  - [ ] Run live wake/voice round trip with body motion locked.
- **Linked ideas**: body-motion policy rubric candidate in `LEARNINGS.md`.

### REQ-002: Reachy meeting prep page + email voice triage
- **Filed**: 2026-04-22
- **Raw ask**: "I want reachy to start to prepare to record my meetings so it needs to pull from my calendar and build that out so I can see, also so I can add to it. Then I also want it to start reviewing my emails and let me know when one comes in and what to do with it, it will ask to read it or ignore, then if I say read it it will read it in a new voice. Also If I say delete or respond it should do that as well."
- **State**: `integrated-awaiting-verify` (**2026-04-24**: 2 days in limbo, still **0/7** verification boxes; code remains uncommitted on working tree)
- **Triage note 2026-04-24**: Primary driver of the Verification Debt metric added this audit. Recommended next action: run the 7-item checklist, decide pass/fail per item, and commit the REQ-002 slab (with the presence-service `datetime.now()` fix included) in a single focused session.
- **Dimensions**: 5 (Meeting Mode), 2 (Voice & Conversation), 4 (Presence & Ambient)
- **Plan**: `C:\Users\hadam\.claude\plans\i-want-reachy-to-moonlit-babbage.md`
- **Workstreams**:
  - **A — Meeting Prep**: `/reachy/meetings` page (`ReachyMeetingsPage.tsx`, `MeetingCard.tsx`, `AddEventDialog.tsx`, `useCalendarApi.ts`); `meeting_auto_recorder_service`; scheduler jobs `reachy_meeting_auto_record` + `reachy_meeting_auto_stop`; endpoints under `/api/meetings/`.
  - **B — Email Voice Triage**: `voice_intent_router`; `email_voice_session_service` (FSM, 60s timeout); `voice_override` on `tts_service.synthesize` / `reachy.say` (reader voice `en-GB-RyanNeural`); `gmail_service.send_email()` + `trash_email()`; `voice_loop_service` short-circuit; `reachy_email.py` router.
- **Decisions baked in**: reader voice = edge-tts `en-GB-RyanNeural`; delete = Gmail Trash; respond = confirm-then-send; 5-min poll; auto-record opt-in per event; parallel build.
- **Non-blocker**: `gmail.modify` scope covers send + TRASH.
- **Verification needed before → `verified`**:
  - [ ] `/reachy/meetings` renders calendar events and accepts new event creation.
  - [ ] Toggling Auto-record on a 2-min-future event triggers recording within ±60s; auto-stops at end_time.
  - [ ] New email arrives → Reachy speaks "from X about Y, read or ignore?" within 5 min.
  - [ ] "read" → body spoken in `en-GB-RyanNeural` (audibly different).
  - [ ] "delete" → email lands in Gmail Trash.
  - [ ] "respond" → spoken intent → LLM draft read back → "send" puts reply in Sent with correct `In-Reply-To`/`threadId`.
  - [ ] 60s silence in any state reverts FSM to idle.
- **Linked ideas**: II-007 (per-persona voice config), II-008 (Gmail Pub/Sub webhook), II-009 (respond-as-persona — cold), II-013 (persona-scoped tool grants — **new, depends on REQ-002 landing**), II-015 (wake-word → email triage — **new, depends on REQ-002 + host_agent**).
- **Notes**: Filed via `/zero-reachy-audit --ask` 2026-04-22. Entered log as `integrated` because code shipped before next audit tick. 2nd audit (2026-04-23) found slab still uncommitted. 3rd audit (2026-04-24) finds it STILL uncommitted — primary Commit-Debt case.

### REQ-001: Deep-dive the Meeting Mode dimension
- **Filed**: 2026-04-22
- **Raw ask**: "I want to focus next on meetings, but I want to run that from a fresh prompt."
- **State**: `planned`
- **Dimension guess**: 5 (Meeting Mode)
- **Current score (2026-04-24)**: B+ (88/100), down from 90. Biggest deficits: coverage 85 (diarization, nod-on-highlight, summary→gesture, persona-aware), freshness 85 (REQ-002 auto-record uncommitted).
- **Triage note 2026-04-24**: `backtoengineering/reachy_mini_object_detector` (HF Space, updated 2026-04-20, new candidate) directly relevant to "look at who's raising their hand". `host_agent/live_transcription.py` (uncommitted) provides a WebSocket broadcast source — II-003 (nod-on-highlight) is now **structurally unblocked** and should be the first concrete task in the REQ-001 plan.
- **Minimum delta**: see `handoffs/2026-04-22-meeting.md`.
- **Blocker**: none — prerequisites (DoA loop, persona swap, recording pipeline, transcript broadcast) all shipped or in-tree.
- **Fresh-prompt kickoff**: paste the block from `handoffs/2026-04-22-meeting.md` into a new Zero session.
- **Linked ideas**: II-002 (meeting-mode persona swap — warm), II-003 (nod on highlight — warm, structurally unblocked), UP-005 (MediaPipe), UP-010 (object detector — **new, hot**).
- **Notes**: Highest-priority capability investment as of 2026-04-22. Still unstarted at 2026-04-24. Pair with REQ-002 verification session to amortise context.

## Archived / verified

### REQ-004: Make Reachy live conversation dependable again
- **Filed**: 2026-05-07
- **Raw ask**: "Go back over and grade each dimension of this from 0 to 100 and get it to 100."
- **State**: `verified`
- **Dimensions**: 1 (Motion & Body), 2 (Voice & Conversation), 3 (Persona & Emotion), 4 (Presence & Ambient), 5 (Meeting Mode), 6 (Environment & Integrations)
- **Root cause**: The daemon/body/realtime provider were healthy, but the Reachy USB microphone path was streaming digital silence while the UI reported it as ready.
- **Integrated fixes**:
  - Realtime input signal classification and no-signal stall reason.
  - Suggested action for silent Reachy mic streams.
  - Frontend automatic fallback from Reachy mic to computer mic.
  - Accurate mic health labels in the live conversation panel.
  - OpenAI Realtime far-field noise reduction and explicit VAD settings.
- **Verification complete**:
  - [x] Backend realtime tests passed.
  - [x] Backend assistant + realtime tests passed together.
  - [x] Frontend Reachy tests passed.
  - [x] Frontend production build passed.
  - [x] `zero-api` rebuilt and healthy.
  - [x] `zero-ui` restarted and healthy.
  - [x] 30 direct daemon/status probes from Docker passed with p95 below 100 ms.
  - [x] Live OpenAI Realtime WebSocket text turn returned assistant transcript `READY`.
  - [x] Host-agent mic stream measured and documented as digital silence; fallback path verified in code and tests.

## Lifecycle guide

| State | Meaning | Transition rule |
|-------|---------|-----------------|
| `pending` | Filed but not yet analyzed | Next audit triages, maps to a dimension, links upstream |
| `researched` | Triaged; upstream + dependencies identified | Promotes when a code plan exists |
| `planned` | Has a handoff doc or execution plan | User/claude action begins |
| `integrated` | Code on `main`, smoke tests pass | Awaits verification on physical robot |
| `integrated-awaiting-verify` | Code works in working-tree but not yet committed / physically tested | Transient; flags Verification Debt if > 48 h |
| `verified` | Live-tested, committed, no regressions | Archive after 30 days |

A request stuck in `pending` >14 days triggers Backlog Debt. A request stuck in `integrated-awaiting-verify` >48 h triggers Verification Debt (new 2026-04-24).

## How to file a new request

```
/zero-reachy-audit --ask "I want Reachy to <thing>"
```
