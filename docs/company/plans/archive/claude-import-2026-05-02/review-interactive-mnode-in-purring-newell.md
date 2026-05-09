# Interactive Mode — fix the cancel-less hang and add real cockpit controls

## Context

The screenshot shows the Reachy Management page stuck in an amber "Connecting…" bar with a "Connecting" button on the right that does nothing. The user reports it "always spins" with no way out, and asks for "a lot more controls here to work through" the page.

Root cause is concrete: there is **no abort path on the connecting state**, on the frontend or the backend.

- [frontend/src/hooks/useRealtimeVoice.ts:276-375](frontend/src/hooks/useRealtimeVoice.ts#L276-L375) sets `state='connecting'` then opens a bare `new WebSocket(...)` with no timeout, no `AbortController`. State only flips to `'connected'` when the backend emits `session.ready` ([useRealtimeVoice.ts:196-200](frontend/src/hooks/useRealtimeVoice.ts#L196-L200)). If `session.ready` never comes (slow upstream, bad key, network hang), the hook never recovers.
- Both UI surfaces hard-block during connecting: [InteractiveModeBar.tsx:125](frontend/src/components/reachy/InteractiveModeBar.tsx#L125) (`if (voice.state === 'connecting') return`) and [InteractiveModeBar.tsx:222](frontend/src/components/reachy/InteractiveModeBar.tsx#L222) (`disabled={connecting}`). Same in the page hero: [ReachyManagementPanels.tsx:225,237](frontend/src/components/reachy/ReachyManagementPanels.tsx#L225-L237) — the orange button literally just says "Connecting" and is disabled.
- Backend [openai_handler.py:139-172](backend/app/services/reachy_realtime/openai_handler.py#L139-L172) does `websockets.connect()` with no `asyncio.wait_for` and retries 3× with exponential backoff. A stalled TLS handshake can park the session for tens of seconds per attempt with no escape.
- Hook's `stop()` ([useRealtimeVoice.ts:377-380](frontend/src/hooks/useRealtimeVoice.ts#L377-L380)) already cleans up correctly — it just isn't reachable from the UI while connecting.

Goal: a working Cancel button on the connecting state, an upstream connect timeout so it can't stall indefinitely, and a real cockpit of controls in the Interactive Mode hero so the user can drive the session (mute, text, swap backend, end, reset, see transcript) without leaving the page.

## Critical files

- [frontend/src/hooks/useRealtimeVoice.ts](frontend/src/hooks/useRealtimeVoice.ts) — add connect timeout + allow `stop()` from `'connecting'`.
- [frontend/src/components/reachy/InteractiveModeBar.tsx](frontend/src/components/reachy/InteractiveModeBar.tsx) — TopBar pill, make it a Cancel button while connecting.
- [frontend/src/components/reachy/ReachyManagementPanels.tsx](frontend/src/components/reachy/ReachyManagementPanels.tsx) — expand `InteractiveModeHero` (lines 70-242) into a cockpit; reuse existing `LLMStatusBadge` and `ReachyRealtimeSettings` rather than rebuilding.
- [frontend/src/components/reachy/LLMStatusBadge.tsx](frontend/src/components/reachy/LLMStatusBadge.tsx) — already has the backend-swap PUT to `/api/reachy/realtime/config`; reuse via shared helper, do not duplicate.
- [backend/app/services/reachy_realtime/openai_handler.py](backend/app/services/reachy_realtime/openai_handler.py) — wrap `websockets.connect()` with `asyncio.wait_for(..., timeout=10)`.
- [backend/app/services/reachy_realtime/gemini_handler.py](backend/app/services/reachy_realtime/gemini_handler.py) — same treatment.

## Plan

### 1. Frontend hook: cancellable connect with timeout

In [useRealtimeVoice.ts](frontend/src/hooks/useRealtimeVoice.ts):

- Add `const CONNECT_TIMEOUT_MS = 12_000` near the other rate constants.
- Add a `connectTimerRef = useRef<number | null>(null)` next to the other refs.
- In `start()` after `setState('connecting')`, schedule:
  ```ts
  connectTimerRef.current = window.setTimeout(() => {
    setError('Connection timed out. Check key, network, or try the other backend.')
    setState('error')
    cleanupEverything()
  }, CONNECT_TIMEOUT_MS)
  ```
- In `handleServerEvent` `case 'session.ready'`, clear the timer.
- In `cleanupEverything`, also clear the timer (covers stop, error, close).
- Relax `stop()` to be a no-op-safe abort that works from any state — current implementation already does this; just remove the early `return` guard in the *callers* (see step 2).
- Bonus: add a `cancel = useCallback(stop, [stop])` alias and export it so call sites read `voice.cancel()` clearly.

### 2. UI: turn the "Connecting" button into a real Cancel

**InteractiveModeBar.tsx (TopBar):**
- Remove the `if (voice.state === 'connecting') return` guard ([line 125](frontend/src/components/reachy/InteractiveModeBar.tsx#L125)) — let `toggle()` call `voice.stop()` when connecting.
- Remove `disabled={connecting}` ([line 222](frontend/src/components/reachy/InteractiveModeBar.tsx#L222)).
- While connecting, show a red `X` icon and label `Cancel` instead of the spinner-only `Connecting…`. Keep the spinner as a small adornment to the left.
- `Esc` should also abort the connecting state, not only the connected state ([line 166](frontend/src/components/reachy/InteractiveModeBar.tsx#L166): widen the condition to `voice.state === 'connected' || voice.state === 'connecting'`).

**InteractiveModeHero (the orange bar from the screenshot):**
- Same fix in `toggle()` ([ReachyManagementPanels.tsx:118-138](frontend/src/components/reachy/ReachyManagementPanels.tsx#L118-L138)) and the button ([line 225,237](frontend/src/components/reachy/ReachyManagementPanels.tsx#L225-L237)). When connecting, render two buttons side-by-side: a primary red "Cancel" and a secondary "Try other backend" that swaps `openai`↔`gemini` via `PUT /api/reachy/realtime/config` and retries.
- Show elapsed connect seconds as `Connecting… (3s)` so the user sees motion and knows when to give up.

### 3. Backend: upstream connect timeout

**openai_handler.py** [`start()` line 139](backend/app/services/reachy_realtime/openai_handler.py#L139):

Wrap the `async with websockets.connect(...)` with `asyncio.wait_for(websockets.connect(...).__aenter__(), timeout=10.0)`, or simpler — keep the `async with` and put the whole attempt under `asyncio.wait_for(self._connect_once(url, headers, client_writer), timeout=10.0)`. On `asyncio.TimeoutError`, log `openai_realtime_connect_timeout`, emit `{type: error, message: 'OpenAI handshake timed out'}`, and continue to the next retry attempt or fail out.

**gemini_handler.py:** same pattern around its upstream connect (find with `grep -n "connect" backend/app/services/reachy_realtime/gemini_handler.py`).

This is the belt to the frontend's suspenders: even if the browser timer is bypassed, the backend won't park forever.

### 4. Cockpit controls in `InteractiveModeHero`

Expand the existing hero (currently icon + title + one button) into a two-row card. Row 1 keeps the live status (already there). Row 2 is a control strip, only rendered when `state !== 'idle'` to keep the off-state minimal:

| Control | Behaviour | Hook / endpoint |
|---|---|---|
| **Backend swap** | Pill showing `OpenAI Realtime` / `Gemini Live`; click cycles, calls `PUT /api/reachy/realtime/config { backend }` from [LLMStatusBadge.tsx:149-152](frontend/src/components/reachy/LLMStatusBadge.tsx#L149-L152). If connected, end + restart. | existing |
| **Voice** | Shows current voice; click opens `ReachyRealtimeSettings` modal (already exists). | existing |
| **Persona** | Shows current profile; click opens persona picker (reuse `PersonaPicker` from the page below). | existing |
| **Mute mic** | Local-only toggle — gates `worklet.port.onmessage` so we stop sending audio frames but keep the WS open. New `voice.muted` + `voice.toggleMute()` in the hook. | hook only |
| **Send text** | Small text input that calls `voice.sendText(text)` (already in the hook, [useRealtimeVoice.ts:382-386](frontend/src/hooks/useRealtimeVoice.ts#L382-L386)). | existing |
| **Cancel response (barge-in)** | When assistant is speaking, button sends `{type: 'cancel_response'}` WS frame. Add `voice.cancelResponse()` to the hook that calls `ws.send(JSON.stringify({type:'cancel_response'}))`. | new tiny method |
| **End / Reset** | "End" calls `voice.stop()`. "Reset" calls stop + immediate `start()` with same args. | existing |
| **Transcript drawer** | Collapsible region under the strip showing last 6 turns from `voice.transcripts` + tool events from `voice.tools`. Already populated by the hook. | existing |
| **Status chips** | `model · voice · profile · ${cost}$ · idle ${remaining}m` — small, monospaced, on the right of the strip. | existing |

Keep it visually compact: control strip is a single horizontal `flex flex-wrap gap-2`, transcript drawer is a `<details>` element so the page doesn't grow unless the user opens it.

### 5. LLM brain picker discoverability

Don't rebuild — instead, render a `<LLMStatusBadge inline />` variant inside the cockpit's status row. Pass a `compact` prop to skip the popover chrome and just expose the dot + label + click target. One line change to `LLMStatusBadge` to honour that prop, plus the new instance in the hero.

### Out of scope (deliberately)

- New backend "force-stop" or "session-info" REST endpoints. The WS `{type:'stop'}` frame plus the new connect timeout cover every observed failure; we can revisit if a future bug shows a session that even the WS-close path can't kill.
- Redesigning the page-wide layout. We extend the existing hero in place; tiles, panels, and library below stay untouched.

## Verification

1. `docker compose -f docker-compose.sprint.yml build --no-cache zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api zero-ui` — the backend handler change requires a rebuild ([CLAUDE.md:Post-Change Deployment]).
2. Open `http://localhost:5173/reachy/management` (or wherever `ReachyMotionLibraryPage` is routed).
3. **Happy path:** click "Talk to Reachy" → connecting bar → live state within ~3s. End session via the new End button.
4. **Cancel works:** point `ZERO_OPENAI_API_KEY` at a bogus value, restart api, click connect → spinner shows for ≤12s then auto-flips to error with a clear message; clicking Cancel during the spin returns to idle within 1s.
5. **Backend timeout works:** with the same bogus key, `docker logs -f zero-api | grep -i realtime` should show `openai_realtime_connect_timeout` (or the bogus-key error) within ~10s, not hang for the full TCP timeout.
6. **Cockpit:** during a live session, exercise mute mic (mic indicator stops moving on the assistant side), send text (assistant replies), swap backend (session restarts on the other provider), cancel response (assistant audio stops mid-sentence), reset (clean restart), open transcript drawer (last turns visible).
7. **Esc:** during connecting and during connected, `Esc` aborts.
8. **No regressions:** `FloatingVoiceButton` push-to-talk still works (separate code path); 5-min idle auto-off still triggers.
