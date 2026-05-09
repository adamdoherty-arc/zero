# Reachy: Match-and-Beat the Native Pollen App

## Context

You remember the default Pollen Robotics Reachy Mini app feeling way snappier than Zero's integration, with an "open API connection out of the box." That memory is correct. The native app (`reachy_mini_conversation_app` at [C:\code\reachy-apps\official\reachy_mini_conversation_app](C:\code\reachy-apps\official\reachy_mini_conversation_app)) is not doing anything magical — it opens a **persistent bidirectional WebSocket to OpenAI Realtime API** (`wss://api.openai.com/v1/realtime?model=gpt-realtime`) or Gemini Live. Audio in, audio out, STT+LLM+TTS all collapsed into one stream. First syllable of the robot's reply arrives in well under a second because:

- Persistent socket (no TLS/auth handshake per turn)
- Server-side VAD decides when your turn ended
- Tokens stream out as 24 kHz PCM chunks, pumped straight into the robot's audio player as they arrive
- Partial user transcripts show up while you're still talking
- Barge-in: speak over the robot and it stops mid-sentence
- Personas enforce 1–2 sentence replies (short output = short playback)

Zero already has this transport wired — [backend/app/routers/reachy_realtime.py](backend/app/routers/reachy_realtime.py), [backend/app/services/reachy_realtime/openai_handler.py](backend/app/services/reachy_realtime/openai_handler.py), [frontend/src/hooks/useRealtimeVoice.ts](frontend/src/hooks/useRealtimeVoice.ts) — but it's the *second* tab in [FloatingVoiceButton.tsx](frontend/src/components/reachy/FloatingVoiceButton.tsx), not the default, and it silently requires an API key. So you've been clicking the left-hand "classic" button (STT → LLM → TTS → daemon upload → play — four sequential hops), which is exactly the experience you're describing.

The two specific bugs compound this:

1. **Wake word never fires.** [host_agent/main.py:112-121](host_agent/main.py#L112-L121) falls back to `WhisperWakeLoop` because `ZERO_PICOVOICE_ACCESS_KEY` is unset. Whisper transcribes whatever it hears (TV, music, room noise) and [wake_word_service.py:30-40](backend/app/services/wake_word_service.py#L30-L40) does a near-exact string match for "hey zero". Effectively never matches.
2. **"Talk to Reachy" stays stuck in "Thinking…".** [voice_loop_service.py:24-26](backend/app/services/voice_loop_service.py#L24-L26) sets per-stage timeouts (STT 15 s, LLM 20 s, TTS 10 s) but `_get_llm_response()` at [line 399-463](backend/app/services/voice_loop_service.py#L399-L463) calls `chat_service` / `unified_llm_client` without wrapping them in `asyncio.wait_for`. If the underlying provider HTTP call stalls (saturated vLLM on :18800, Kimi slow, local Ollama swapping a model), nothing unwinds. The outer 48 s router timeout [reachy.py:1097-1133](backend/app/routers/reachy.py#L1097-L1133) only fires on the response, not on a hung upstream. Frontend `fetch` has no `AbortController` deadline so it waits as long as the TCP socket stays alive.

## Recommended Approach

Four focused workstreams. A and B are the unlock — together they make the Talk-to-Reachy button feel like the native app. C and D keep everything you've added (personas, gestures, memory, vault) working with the new fast path.

### Workstream A — Make Realtime the primary voice path, not an opt-in

The realtime pipeline already exists. Promote it.

- In [FloatingVoiceButton.tsx](frontend/src/components/reachy/FloatingVoiceButton.tsx): flip the default mode from `classic` to `realtime` when `realtimeAvailable === true`. Keep classic as the fallback only when no realtime key is configured. Ctrl+Shift+J should also prefer realtime.
- In [reachy_realtime.py](backend/app/routers/reachy_realtime.py) `/realtime/config` endpoint: return `preferred_backend` based on which key is present (`GEMINI_API_KEY` first because Gemini Live is cheap, `OPENAI_API_KEY` second for `gpt-realtime` quality). Surface this so the button can default to whichever is ready.
- Bridge gestures into realtime so you don't regress what you built. The native app does this with a `background tool manager` ([C:\code\reachy-apps\...\bg_tool_manager.py](C:\code\reachy-apps\official\reachy_mini_conversation_app\bg_tool_manager.py)). Mirror the pattern in [reachy_realtime/session.py](backend/app/services/reachy_realtime/session.py):
  - Register the existing gesture markers (`[emotion:...]`, `[dance:...]`, `[look:...]`) as **OpenAI Realtime function-call tools** (`play_emotion`, `play_dance`, `look_at`, `search_vault`, `get_briefing`).
  - When OpenAI emits a `response.function_call_arguments.done` event, fire the corresponding `reachy_service` / `chat_service` call on a background task. Don't block the audio stream.
  - Add the same `parse_and_strip()` fallback from [voice_loop_service.py](backend/app/services/voice_loop_service.py) so inline text markers still work if the model emits them instead of calling the tool.
- Also bridge Zero-specific features as tools so realtime mode gains, not loses, capability: `search_vault`, `get_briefing`, `start_meeting`, `save_note`, `get_calendar`. Reuse the MCP tool definitions already in [mcp_servers/zero_api_mcp.py](mcp_servers/zero_api_mcp.py) — they convert 1:1 to Realtime tool specs.
- Barge-in: in [frontend/src/lib/reachy-realtime-audio.ts](frontend/src/lib/reachy-realtime-audio.ts), on any `input_audio_buffer.speech_started` event from the server, clear the browser's pending playback queue and cancel any in-flight `play_sound` on the daemon via `/api/reachy/media/stop` (add that endpoint if it doesn't exist — `reachy_service` already owns `/api/media/release`).
- Short-response persona: ensure `session.update` sends `instructions` that ends with "Respond in 1–2 sentences, under 25 words unless user asks for more." Copy verbatim from the native app's `cosmic_kitchen` instructions.

### Workstream B — Kill the "Thinking…" hang on classic path

Classic mode still has to work (no API key, offline, etc.). Make it impossible for it to hang longer than ~15 seconds, and make failures visible.

- **Backend hard ceiling.** In [voice_loop_service.py:399-463](backend/app/services/voice_loop_service.py#L399-L463) wrap the LLM call with `asyncio.wait_for(..., timeout=_LLM_TIMEOUT)` **inside** `_get_llm_response`, not outside. If it fires, return a canned "I got stuck, try again" string and log the provider that stalled. Same treatment for `_safe_synthesize` (TTS).
- **Underlying HTTP timeouts.** `unified_llm_client` and `chat_service` must pass `timeout=httpx.Timeout(connect=2.0, read=15.0, write=5.0, pool=2.0)` to whichever HTTP client they use. If they don't (check both), patch them. Provider-level hangs are what actually bypass the `asyncio.wait_for` otherwise — a socket that never sends bytes stays "awake" until OS TCP keepalive times out (minutes).
- **Frontend deadline + visible state.** In [FloatingVoiceButton.tsx:164-191](frontend/src/components/reachy/FloatingVoiceButton.tsx#L164-L191), pass an `AbortController` with a 45 s timeout to `callApi('/voice/stop')`. On abort, show a toast "Reachy is slow — trying realtime mode" and offer a one-click switch to realtime if available. Also add a visible countdown ("Thinking… 12s") so a stall is obvious instead of mysterious.
- **Fallback chain.** If the classic path fails twice in a row, auto-promote realtime to default for this session (store in Zustand).

### Workstream C — Fix the wake word

Two-path fix. Quickest win first.

- **Get a free Picovoice key.** Picovoice offers a free access key at https://console.picovoice.ai/ (personal use, rate-limited but fine for one user). Set `ZERO_PICOVOICE_ACCESS_KEY=<key>` in `.env`, keep `ZERO_WAKE_KEYWORD=jarvis` (it's a free built-in keyword). `host_agent/main.py:167-191` will then start `WakeLoop` (Porcupine) instead of `WhisperWakeLoop`. Porcupine is millisecond-latency and near-zero false positives because it's trained per-keyword, not ASR-based.
  - If you want "hey reachy" specifically: Picovoice's free tier also lets you train one custom keyword at https://console.picovoice.ai/ppn — export the `.ppn` file, set `ZERO_PICOVOICE_KEYWORD_PATH=/path/to/hey_reachy_windows.ppn`, update `WakeLoop` in [host_agent/wake_loop.py](host_agent/wake_loop.py) to pass it via `keyword_paths=`.
- **Fix the whisper fallback** so it's not useless when Picovoice is unavailable. In [wake_word_service.py:30-40](backend/app/services/wake_word_service.py#L30-L40):
  - Lowercase + strip punctuation before match.
  - Replace exact-match with `rapidfuzz.fuzz.partial_ratio(phrase, text) > 80` (add `rapidfuzz` to backend deps — it's ~1 MB, pure Rust).
  - Require a **minimum audio energy** gate before transcription runs (skip whisper on silence/background music). Add RMS check in [host_agent/whisper_wake_loop.py](host_agent/whisper_wake_loop.py) — the native app uses `-35 dBFS` as its VAD on-threshold ([speech_tapper.py:18-19](C:\code\reachy-apps\official\reachy_mini_conversation_app\audio\speech_tapper.py#L18-L19)), reuse that number.
  - Also reject matches where the transcribed chunk is > 8 words (if whisper returned a full sentence of TV dialogue that happens to contain "zero", that's not a wake event).
- **Surface wake status in UI.** The backend endpoint `/api/reachy/wake-word/predict` exists but there's no indicator anywhere. Add a small LED dot next to [FloatingVoiceButton](frontend/src/components/reachy/FloatingVoiceButton.tsx) driven by a new `/api/host-agent/wake/status` passthrough (host_agent already exposes `_wake_mode_actual`). Green = porcupine, yellow = whisper, grey = off. Makes regressions impossible to miss.

### Workstream D — Classic-mode responsiveness parity

Even after A, classic will be the fallback. Shorten it.

- Port the native app's persona rule into [voice_loop_service.py:401-428](backend/app/services/voice_loop_service.py#L401-L428): append "Keep replies to 1–2 sentences, under 25 words, unless I explicitly ask for detail" to the system prompt for voice turns (not for text turns — keep the vault/briefing responses long). The current personas inherited from Pollen already enforce this; make sure the zero persona list does too. Check [reachy_personas.py:52-200](backend/app/services/reachy_personas.py#L52-L200) and add the rule to any persona missing it.
- Pre-warm faster-whisper on [backend/app/main.py](backend/app/main.py) startup so first-turn STT isn't a cold-start spike. `audio_service.transcribe_upload(silence_bytes)` once at boot.
- Pre-warm edge-tts by synthesizing a 2-char string on boot. First edge-tts call currently takes 5–10 s (you already noted this in [reachy_service.py:543](backend/app/services/reachy_service.py#L543)).
- Fire TTS and motion in parallel, not sequentially. `voice_loop_service.py` already uses `asyncio.create_task` for gestures — confirm the TTS upload happens while the LLM is finishing rather than after.

## Files to touch

**Workstream A**
- [frontend/src/components/reachy/FloatingVoiceButton.tsx](frontend/src/components/reachy/FloatingVoiceButton.tsx) — default mode + key prompt UX
- [frontend/src/lib/reachy-realtime-audio.ts](frontend/src/lib/reachy-realtime-audio.ts) — barge-in playback-queue clear
- [frontend/src/hooks/useRealtimeVoice.ts](frontend/src/hooks/useRealtimeVoice.ts) — handle `function_call` events → call `/api/reachy/...`
- [backend/app/routers/reachy_realtime.py](backend/app/routers/reachy_realtime.py) — `preferred_backend` in `/config`
- [backend/app/services/reachy_realtime/session.py](backend/app/services/reachy_realtime/session.py) — tool registration + dispatch
- [backend/app/services/reachy_realtime/openai_handler.py](backend/app/services/reachy_realtime/openai_handler.py) — session.update instructions

**Workstream B**
- [backend/app/services/voice_loop_service.py](backend/app/services/voice_loop_service.py) — `asyncio.wait_for` wrap
- [backend/app/infrastructure/unified_llm_client.py](backend/app/infrastructure/unified_llm_client.py) — httpx timeout
- [backend/app/services/chat_service.py](backend/app/services/chat_service.py) — httpx timeout
- [frontend/src/components/reachy/FloatingVoiceButton.tsx](frontend/src/components/reachy/FloatingVoiceButton.tsx) — AbortController + countdown

**Workstream C**
- `.env` + [.env.example](.env.example) — `ZERO_PICOVOICE_ACCESS_KEY`
- [backend/app/services/wake_word_service.py](backend/app/services/wake_word_service.py) — rapidfuzz + energy gate + word-count guard
- [backend/requirements.txt](backend/requirements.txt) — add `rapidfuzz`
- [host_agent/whisper_wake_loop.py](host_agent/whisper_wake_loop.py) — RMS gate
- [frontend/src/components/reachy/FloatingVoiceButton.tsx](frontend/src/components/reachy/FloatingVoiceButton.tsx) — status dot

**Workstream D**
- [backend/app/services/voice_loop_service.py](backend/app/services/voice_loop_service.py) — short-reply system prompt suffix
- [backend/app/services/reachy_personas.py](backend/app/services/reachy_personas.py) — enforce rule on all personas
- [backend/app/main.py](backend/app/main.py) — startup warm-up calls

## Existing utilities to reuse (do not rewrite)

- Gesture parsing: `parse_and_strip()` in [voice_loop_service.py](backend/app/services/voice_loop_service.py)
- MCP tool definitions for realtime tool specs: [mcp_servers/zero_api_mcp.py](mcp_servers/zero_api_mcp.py)
- Reachy daemon REST client: [backend/app/services/reachy_service.py](backend/app/services/reachy_service.py) — `move_head`, `play_sound`, `media_release`
- Personas catalog: [backend/app/services/reachy_personas.py](backend/app/services/reachy_personas.py)
- Native app reference (read-only, for patterns): [C:\code\reachy-apps\official\reachy_mini_conversation_app\bg_tool_manager.py](C:\code\reachy-apps\official\reachy_mini_conversation_app\bg_tool_manager.py), `speech_tapper.py`, `prompts.py`

## Verification

Run after each workstream. No "type-check passes" declarations — all tests must be feature tests.

**A — Realtime-as-default**
1. `docker compose -f docker-compose.sprint.yml build --no-cache zero-api && ... up -d zero-api zero-ui`
2. Open `http://localhost:5173`, click the floating voice orb. Expect it to connect to realtime on first click (assuming a key is set). Time first-audio-response: must be < 1.2 s from end-of-speech.
3. Say "play your dance move". Verify the robot actually dances (tool call fired) while speaking the response.
4. Interrupt mid-response ("wait, stop"). Robot audio must cut within 300 ms.
5. Say "search my vault for X". Verify `search_vault` tool fires and result is spoken back.

**B — No more hangs**
1. Temporarily kill vLLM on :18800 (`docker stop zero-vllm` or equivalent) to simulate a wedged provider.
2. Fall back to classic (toggle off realtime). Click Talk, speak, stop.
3. Expected: within 17 s, toast appears: "Reachy is slow — trying realtime mode". State returns to idle. No permanent "Thinking…".
4. Restart vLLM, retry — classic should work again, sub-5 s turnaround.

**C — Wake word**
1. After setting `ZERO_PICOVOICE_ACCESS_KEY`, restart host_agent. Log should show `wake_mode_actual=porcupine`. Status dot in UI shows green.
2. Say "jarvis, what time is it". Robot should respond within 2 s of the keyword.
3. Play a podcast / TV near the mic. Verify no false wakes over 5 minutes (previously every other sentence triggered a scan).
4. Without Picovoice key (whisper fallback): say "hey zero". Verify match. Play a sentence containing "zero" buried in other words — should NOT match (word-count guard).

**D — Classic speedup**
1. End-to-end classic turn: full round-trip (mic press → end-of-audio → first robot-audio-byte) should be < 4 s with pre-warmed models, vs. 8–10 s cold-start currently.
2. Responses should be 1–2 sentences unless user says "explain in detail".

## Open decision for you

One thing I need to confirm before implementing A: **which realtime backend do you want as the default** — OpenAI (`gpt-realtime`, higher quality, ~$0.30/10-min conversation) or Gemini Live (`gemini-3.1-flash-live-preview`, much cheaper, voice slightly more robotic)? Your `.env` already has both keys historically. If I don't hear a preference I'll default to **Gemini Live for always-on** and let a settings toggle switch to OpenAI for "serious" conversations. That matches your "interact with on a daily basis" framing.

## Continued research directions (for next pass, not this one)

You asked me to keep researching. Things I noticed worth investigating after the above ships:

- **Local realtime alternative.** There's a growing ecosystem of streaming STT + streaming TTS + local LLM that mimics OpenAI Realtime without network dependency: `ultravox`, `qwen2-audio`, `kyutai/moshi`. Moshi in particular is a single-model streaming voice LLM (sub-200 ms latency). Worth a spike once API costs matter.
- **Reachy onboard mic over HTTP.** You currently use the host's "Echo Cancelling Speakerphone (Reachy Mini Audio)" USB device. The daemon may also expose the onboard array mic over HTTP/WebSocket — that would let you move voice input onto the robot, freeing the host mic for other uses.
- **Emotional prosody.** OpenAI Realtime supports `voice_settings` with style tags. Map the `[emotion:...]` markers you already parse to voice style at session update time so the *speech itself* carries the emotion, not just the head motion.
- **Multi-turn memory into Realtime.** The native app has no cross-session memory. Zero does (vault + notes). Inject the last 5 turns of cross-session context into the realtime session's initial `instructions` on connect, so Reachy "remembers" yesterday.

---

# Phase F — Interactive Mode + LLM Visibility

## Context

Current pain (quoting you): *"The other app just put the robot in a mode that we could talk back and forth very natively. It is telling me to switch models that local LLM is down. I still have no controls to switch what LLM is using so I have no idea, this was supposed to be surfaced in the UI."*

Three concrete gaps from the audit:

1. **Interactive Mode is buried.** Realtime mode exists and works, but lives inside the settings cog as one of two buttons. There's no primary "Talk to Reachy live" surface the way the native Pollen app has — you have to open settings, pick a mode, then click the mic. When Interactive Mode IS on, there's no persistent indicator that the robot is actively listening except the button color.
2. **LLM provider controls are hidden two clicks deep** ([FloatingVoiceButton.tsx:416-451](frontend/src/components/reachy/FloatingVoiceButton.tsx)). The provider switcher exists (`/api/reachy-intent/providers` GET + POST) but you'd have to know to open the gear → scroll → find the Classic list. There's no health indicator — the only way you learn vLLM is down is a failed voice command 22 seconds later.
3. **Error toasts are generic.** When the classic path fails, backend logs every provider it tried and why, but [reachy_intent.py:383](backend/app/routers/reachy_intent.py) only returns `last_error` as a string. The toast reads "I can't reach any chat model right now" — no indication of which provider failed or offered alternative.

## Recommended approach

Four surfaces that together give you the native-app feel:

### F1 — Interactive Mode: primary top-of-page toggle

A persistent pill-style switch at the top of every Reachy-related page (Motion Library, Teleop, Meetings, plus the main dashboard) rather than buried in a floating-button gear.

- **Component**: new `frontend/src/components/reachy/InteractiveModeBar.tsx`. Full-width bar, 40 px tall, fixed at top when on a Reachy page. Left side: "Interactive Mode" label + large toggle switch. Right side: active LLM badge + mic level meter + session duration + cost counter + big red "End session" button.
- **States** driven by [useRealtimeVoice.ts](frontend/src/hooks/useRealtimeVoice.ts): `off` (grey) / `connecting` (pulsing amber) / `listening` (emerald, gentle pulse) / `speaking` (indigo, animated waveform icon) / `error` (red with retry button).
- **Click behavior**: single click toggles the realtime WebSocket session — same code path `voice.start()` / `voice.stop()` already used by FloatingVoiceButton. No settings-cog navigation required.
- **Robot "alive" state**: when Interactive Mode enters `listening`, dispatch a lightweight ambient motion on the daemon — `reachy_service.play_emotion("attentive1")` — so the robot visibly enters the conversation. Exit animation on `off`.
- **Idle auto-off** (critical for cost): if no voice activity for 5 min (configurable via `ZERO_REACHY_INTERACTIVE_IDLE_TIMEOUT`), auto-disconnect with a toast "Reachy went idle — click to resume". Tracks last user-speech-started event from the existing `user.speech_started` frame.

### F2 — Always-visible LLM status badge

Small clickable badge right inside the Interactive Mode bar (and a mirror in the floating button for classic mode users).

- **Component**: new `frontend/src/components/reachy/LLMStatusBadge.tsx`. Shows `⬤ Gemini Live` (green dot + model name) or `⬤ vLLM local (down)` (red dot).
- **Click opens a popover** — a dense provider list grouped by category:
  - **Interactive (realtime):** OpenAI Realtime (`gpt-realtime`), Gemini Live (`gemini-3.1-flash-live-preview`)
  - **Classic (push-to-talk):** vLLM local, Gemini Flash, Gemini Pro, Kimi Light, Kimi K2.5
  - Each row: dot (green/yellow/red from health probe) + label + est. cost/min + one-click "Use this one".
- **Switch while live**: selecting a new backend while the realtime session is active gracefully stops the current WebSocket and restarts with the new backend — user keeps talking, no page reload.
- **Reuses** existing endpoints `/api/reachy-intent/providers` (classic) and `PUT /api/reachy/realtime/config` (realtime backend). No new backend state to store.

### F3 — Provider health probes + structured error reporting

Backend additions so the badge's red/green dots are accurate, and so a failed voice turn tells the user exactly which provider failed.

- **New endpoint** `GET /api/reachy-intent/providers/status` in [reachy_intent.py](backend/app/routers/reachy_intent.py): concurrently probes each provider with a 1-second "ping" prompt ("say ok"), returns `[{id, ok: bool, latency_ms: int, error?: str}]`. Cache result for 15 s to avoid burning tokens on every poll. Frontend polls every 20 s while Interactive Mode is open, every 60 s otherwise.
  - Reuse `get_unified_llm_client()` with `asyncio.wait_for(..., timeout=1.0)` and a 1-token `max_tokens` cap so cost is negligible.
- **Structured error envelope**: extend `IntentResponse` pydantic model in [reachy_intent.py:41-45](backend/app/routers/reachy_intent.py) with `tried_providers: list[{id, status, error?}]` populated inside `_handle_chat` as the fallback chain walks. Frontend toast becomes "Tried vLLM (timeout), Gemini Flash (down). Switch to Kimi?" with an inline button that hits `POST /providers`.
- **Push status over the live WebSocket** while Interactive Mode is connected: wire a `provider.status` event through [reachy_realtime/session.py](backend/app/services/reachy_realtime/session.py) that the realtime handlers emit when they encounter auth/quota errors, so the badge flips red in real time instead of on the next poll tick.

### F4 — Native-app-style feedback polish

Small things that together make it feel alive.

- **Partial transcripts in the Interactive Mode bar** (from the existing `user.speech_started` + transcript events) so you see your own words appearing as you speak.
- **Assistant "speaking" waveform**: when `audio.delta` frames are arriving, animate a 3-bar EQ icon in the badge. Purely visual; the frames already flow through [scheduleSpeakerFrame()](frontend/src/hooks/useRealtimeVoice.ts).
- **Session duration + running cost**: `voice.cost` is already tracked; surface it in the bar. Lets you glance at the freebie quota burn.
- **Keyboard**: `Space` (when not typing) toggles Interactive Mode, `Esc` ends session. `Ctrl+Shift+J` stays as the alternate.
- **CLAUDE.md entry**: document that Interactive Mode is the primary voice UX so future assistants don't re-surface classic mode as default.

## Files to create / modify

**New**
- `frontend/src/components/reachy/InteractiveModeBar.tsx` — the top-of-page pill
- `frontend/src/components/reachy/LLMStatusBadge.tsx` — badge + switch popover
- `frontend/src/hooks/useProviderStatus.ts` — React Query hook that polls `/providers/status`

**Modify**
- [frontend/src/layouts/](frontend/src/layouts/) — mount `<InteractiveModeBar />` in the main dashboard layout so it's on every screen that touches Reachy
- [frontend/src/hooks/useRealtimeVoice.ts](frontend/src/hooks/useRealtimeVoice.ts) — add `sessionDurationSec`, `lastVoiceActivityAt`, idle-timer autoloud, and a new `switchBackend()` method that stops+restarts
- [frontend/src/components/reachy/FloatingVoiceButton.tsx](frontend/src/components/reachy/FloatingVoiceButton.tsx) — strip the mode-toggle from the gear (redundant once F1 ships) and replace with a link "Manage in Interactive Mode bar"
- [backend/app/routers/reachy_intent.py](backend/app/routers/reachy_intent.py) — new `GET /providers/status` endpoint + `tried_providers` on `IntentResponse`
- [backend/app/services/reachy_realtime/session.py](backend/app/services/reachy_realtime/session.py) — emit `provider.status` frame on auth/quota errors from the handlers
- [backend/app/services/reachy_realtime/openai_handler.py](backend/app/services/reachy_realtime/openai_handler.py) and [gemini_handler.py](backend/app/services/reachy_realtime/gemini_handler.py) — surface quota/auth failures through the new channel

## Existing utilities to reuse (do not rewrite)

- Provider catalog: [backend/app/services/reachy_chat_provider.py:37-73](backend/app/services/reachy_chat_provider.py) — already has id/label/provider/model/description for each option
- Realtime config store: [backend/app/services/reachy_realtime/config_store.py](backend/app/services/reachy_realtime/config_store.py) — already persists backend/voice/profile choice
- `user.speech_started` event already emitted by [openai_handler.py:297-303](backend/app/services/reachy_realtime/openai_handler.py) — drives both the listening indicator and the idle-timer reset
- LLM router resolver: [llm_router.py `resolve_provider_model`](backend/app/infrastructure/llm_router.py) — use for the health probe so we test exactly what voice_loop will use
- Motion dispatch for "attentive1": [reachy_service.play_emotion](backend/app/services/reachy_service.py)

## Verification

Per-deliverable, all feature tests (not type-check passes).

**F1 — Interactive Mode bar**
1. Rebuild both containers. Load any Reachy page.
2. Confirm the bar is visible at top, toggle is OFF on first load.
3. Click the toggle. Within 1.5 s the bar should transition to `connecting` → `listening`. Robot should play the `attentive1` emotion (head tilt).
4. Speak. Partial transcript appears in real time in the bar. Assistant replies. Waveform icon animates during speech.
5. Don't speak for 5 min. Session auto-disconnects, toast appears. Toggle re-enters `off`.
6. Repeat with the daemon stopped — bar should degrade gracefully (session still works, robot "alive" motion is skipped).

**F2 — LLM badge**
1. Open the badge popover. Every provider has a colored dot.
2. Stop `vLLM` container → within 20 s the vLLM dot flips red.
3. Restart `vLLM` → within 20 s it flips green.
4. While in Interactive Mode, switch from Gemini Live to OpenAI Realtime via the popover. Session cleanly restarts under 2 s. Transcripts continue from where they left off.
5. While in Classic mode, switch vLLM → Gemini Pro via the popover. Next `/voice/stop` uses Gemini Pro (verify via the `detail.provider_id` field in the response).

**F3 — Structured errors**
1. Stop all providers except one. Fire classic voice. Response should include `detail.tried_providers = [{id:"vllm", status:"timeout"}, {id:"gemini-flash", status:"failed"}, ...]`.
2. Toast shows "Tried vLLM (timeout), Gemini Flash (down). Switch to Kimi K2.5?" with one-click button.
3. Click the button. `POST /providers` fires. Next voice turn uses Kimi K2.5.
4. Hit OpenAI Realtime quota limit during Interactive Mode. Badge turns red within 2 s (pushed via the WebSocket, not polled).

**F4 — Polish**
1. Press `Space` on the dashboard (not while in a text field). Interactive Mode toggles.
2. `Esc` during an active session ends it cleanly.
3. Running cost ticks up during a session; matches `voice.cost` from the hook.
4. Robot visibly enters a baseline head-sway when Interactive Mode is listening (via the existing `AsyncHeadWobbler`).

## Open decision for you

One choice that meaningfully changes the UX shape. Pick one and I'll build to it:

**Option A — Single top bar (my recommendation):** the full-width Interactive Mode bar described above is THE primary voice UI. The floating mic button shrinks to a secondary push-to-talk button (classic mode only) for moments when you don't want to leave realtime running. This matches the native app — one clear "alive" state, one clear "off" state.

**Option B — Mini dock in the sidebar:** Interactive Mode toggle lives as a compact card in the left sidebar alongside Sprints / Tasks / etc., with the same state visualization but narrower. Floating button stays primary for push-to-talk. Less visible but less invasive if you don't want Reachy UI dominating screens that have nothing to do with the robot.

**Option C — Leave FloatingVoiceButton, add only the LLM badge:** minimal change — just the badge + health probes + structured errors. No new bar. Cheapest ship, least UX transformation. Good if you want to keep iterating on the voice button and only solve the "I can't see what LLM I'm using" problem.

Default if you don't reply: **A**, because it directly addresses your "put the robot in a mode where we talk back and forth natively" ask.

