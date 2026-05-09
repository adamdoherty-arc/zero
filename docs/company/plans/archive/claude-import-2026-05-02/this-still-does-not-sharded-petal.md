# Reachy Voice — Fix the Loop, Surface Models, Modernize the UI

## Context

The user is looking at the Reachy conversation panel showing `stt 19.6s`, `tts 11.1s`, and the fallback line "I had trouble hearing that. Could you try again?" They have three concrete complaints:

1. The voice loop still doesn't work.
2. They can't choose which models (STT / LLM / TTS) are used.
3. They can't see which model is currently running.
4. The UI feels "old" — a lot of backend work isn't surfaced.

### Root causes found during exploration

**Why it fails.** [backend/app/services/voice_loop_service.py:24](backend/app/services/voice_loop_service.py#L24) sets `_STT_TIMEOUT = 15.0`, but the host_agent Whisper model is lazy-loaded on first request ([host_agent/voice_capture.py:169-177](host_agent/voice_capture.py#L169-L177)), so the first turn after daemon start spends ~9-10 s loading `base` before transcription. Total 19.6 s > 15 s timeout → fallback `_FALLBACK_STT` ([voice_loop_service.py:30](backend/app/services/voice_loop_service.py#L30)) fires. TTS has the same lazy-load problem via Piper in [backend/app/services/tts_service.py:32,124-142](backend/app/services/tts_service.py#L32).

**Why models can't be picked.** Backend has the infrastructure — [backend/app/routers/llm.py](backend/app/routers/llm.py) exposes `/api/llm/config`, `/api/llm/task/{type}`, `/api/llm/available-models`, and [backend/app/infrastructure/llm_router.py](backend/app/infrastructure/llm_router.py) persists assignments to `workspace/llm/router_config.json`. Voice pipeline resolves LLM via `task_type="voice_reply"` ([backend/app/services/voice_loop_service.py:399-474](backend/app/services/voice_loop_service.py#L399)). STT model is env-only (`ZERO_WAKE_WHISPER_MODEL`, default `base`). TTS voice is env-only (`TTS_MODEL`). There is zero UI wiring for any of them.

**Why the UI feels old.** [frontend/src/pages/ReachyMotionLibraryPage.tsx](frontend/src/pages/ReachyMotionLibraryPage.tsx) renders `phase_log` badges with phase + ms only — no `provider`/`model` metadata even though [unified_llm_client.py:687-698](backend/app/infrastructure/unified_llm_client.py#L687) logs them. Realtime voice config (`/api/reachy/realtime/*`) is buried in `FloatingVoiceButton` — not reachable from the main hub. `/radio/*` endpoints have no UI. No dedicated voice-settings page.

## Approach

Five changes, each small and self-contained. Ship all of them.

### A. Fix the voice loop — eliminate cold starts, not just raise timeouts

- **Pre-warm Whisper at host_agent startup.** In [host_agent/main.py](host_agent/main.py) startup event, call `VoiceCapture._load_whisper()` before the first request. Log model+device+load_ms for visibility.
- **Pre-warm Piper at zero-api startup.** In [backend/app/services/tts_service.py](backend/app/services/tts_service.py), expose `warmup()`; call from [backend/app/main.py](backend/app/main.py) startup. Synthesize a 1-word sample so the model caches in memory.
- **Default STT to `tiny`**, not `base`. For Reachy's echo-cancelling mic the accuracy gap is negligible and load+transcribe drops from ~19 s to ~2 s. Change [host_agent/main.py:131](host_agent/main.py#L131) default + document that `ZERO_WAKE_WHISPER_MODEL` overrides it.
- **Raise `_STT_TIMEOUT` to 25 s** ([voice_loop_service.py:24](backend/app/services/voice_loop_service.py#L24)) as a safety net for first-boot or larger-model selections. The pre-warm is the real fix; the raised timeout just prevents a one-off cold start from looking broken.

### B. Return model metadata per turn

- Extend the `phase_log` entry shape from `{phase, ms, ok, error?}` to `{phase, ms, ok, error?, provider?, model?}`.
  - STT phase: `provider="faster-whisper"`, `model=<current whisper model>`. Host_agent already knows; [backend/app/services/voice_loop_service.py:150-165](backend/app/services/voice_loop_service.py#L150) builds the entry — plumb the model through `transcribe_upload` return.
  - LLM phase: `unified_llm_client.chat()` returns the resolved provider+model in its result; [voice_loop_service.py](backend/app/services/voice_loop_service.py) already has it — just copy into the phase entry.
  - TTS phase: `tts_service.synthesize()` returns which engine + voice actually ran; carry into the phase entry.
- Add `result["active_models"] = {"stt": ..., "llm": ..., "tts": ...}` to the voice response envelope so the UI can render a persistent header even before a turn completes.

### C. Voice-config backend — one router, persists to JSON

New file `backend/app/routers/reachy_voice_config.py`:

- `GET /api/reachy/voice/config` → `{stt_model, llm_model, tts_voice}`. LLM value is the current resolution of `task_type="voice_reply"` via `LlmRouter.resolve_provider_model("voice_reply")`.
- `PUT /api/reachy/voice/config` → accepts any subset of `{stt_model, llm_model, tts_voice}`. Persists to `workspace/reachy/voice_config.json` (use existing `JsonStorage` utility). Side effects:
  - `stt_model` → `POST http://host.docker.internal:18794/voice/config` with new model name (new endpoint in host_agent, below).
  - `llm_model` → `router.set_task_model("voice_reply", provider, model)` (reuses existing [llm_router.py](backend/app/infrastructure/llm_router.py)).
  - `tts_voice` → update in-memory `tts_service._voice` + persist.
- `GET /api/reachy/voice/models` → enumerates choices:
  - STT: `["tiny", "base", "small", "medium", "large-v3"]` from [backend/app/routers/audio.py:23-30](backend/app/routers/audio.py#L23).
  - LLM: call existing `/api/llm/available-models` handler.
  - TTS: scan Piper voices directory; fall back to a hard-coded shortlist (`en_US-lessac-medium`, `en_US-amy-medium`, `en_GB-alba-medium`).

Host_agent addition in [host_agent/main.py](host_agent/main.py): `POST /voice/config` accepting `{whisper_model}` — drops the cached VoiceCapture, starts a fresh one with the new model, pre-warms it, returns `{ok, load_ms}`.

Register the new router in [backend/app/main.py](backend/app/main.py) alongside the other Reachy routers.

### D. Frontend — upgrade the conversation panel + add a settings drawer

**`ReachyMotionLibraryPage.tsx` PushToTalk block:**
- The phase badge at line ~344 gets `{p.model && <span className="opacity-60">{p.provider}/{p.model}</span>}`. Example rendered output: `stt 2.1s · faster-whisper/tiny`.
- A new "active stack" row above the conversation shows `STT whisper/tiny · LLM kimi/kimi-k2.6 · TTS piper/lessac-medium`, fed by the latest turn's `active_models` or by a standalone `GET /api/reachy/voice/config` call on mount.
- Gear icon opens a `<VoiceModelSettings />` drawer.

**New component `frontend/src/components/reachy/VoiceModelSettings.tsx`:**
- Three labeled dropdowns (STT / LLM / TTS) populated from `GET /api/reachy/voice/models`.
- Current selections pre-populated from `GET /api/reachy/voice/config`.
- On change: `PUT /api/reachy/voice/config` with the single changed field; toast the new value; invalidate `voiceConfig` query key.
- Second section for Realtime voice: backend (`openai` / `gemini`), voice profile, model — `GET`/`PUT /api/reachy/realtime/config` (already exists but unsurfaced).

**New hook `frontend/src/hooks/useReachyVoiceConfig.ts`:** React Query wrappers for the two GETs and the PUT, following the existing query-key-factory pattern.

### E. Close the "UI seems old" gap — two new pages + sidebar entries

Both are thin: they compose existing components and hit already-live endpoints.

- **`frontend/src/pages/ReachyVoiceSettingsPage.tsx`** at route `/reachy/voice-settings` — the canonical full-page view of `VoiceModelSettings`, with an additional section showing recent voice-turn latencies from the DB (reuses existing llm_usage table filtered by `task_type="voice_reply"`).
- **`frontend/src/pages/ReachyRadioPage.tsx`** at route `/reachy/radio` — start / stop / analyze controls calling the existing `/api/reachy/radio/*` endpoints. One component per endpoint; no new backend work.
- **Sidebar** ([frontend/src/components/Sidebar.tsx](frontend/src/components/Sidebar.tsx) or equivalent): add "Voice Settings" and "Radio" entries under the Reachy section.
- Register both routes in [frontend/src/App.tsx](frontend/src/App.tsx).

Character Reference Videos and Ambient Scheduler are also mentioned in recent commits but not in scope for this change — they get their own pass if asked.

## Critical files to modify

Backend:
- [backend/app/services/voice_loop_service.py](backend/app/services/voice_loop_service.py) — timeout, phase_log shape, active_models
- [backend/app/services/tts_service.py](backend/app/services/tts_service.py) — `warmup()`, return engine+voice metadata
- [backend/app/services/audio_service.py](backend/app/services/audio_service.py) — return model metadata from transcription
- [backend/app/routers/reachy_voice_config.py](backend/app/routers/reachy_voice_config.py) — NEW
- [backend/app/main.py](backend/app/main.py) — register router, warmup on startup
- [host_agent/main.py](host_agent/main.py) — startup warmup, `/voice/config` endpoint, default model → `tiny`
- [host_agent/voice_capture.py](host_agent/voice_capture.py) — pre-warm hook, return model name from transcribe

Frontend:
- [frontend/src/pages/ReachyMotionLibraryPage.tsx](frontend/src/pages/ReachyMotionLibraryPage.tsx) — conversation panel upgrade, gear icon
- [frontend/src/components/reachy/VoiceModelSettings.tsx](frontend/src/components/reachy/VoiceModelSettings.tsx) — NEW
- [frontend/src/pages/ReachyVoiceSettingsPage.tsx](frontend/src/pages/ReachyVoiceSettingsPage.tsx) — NEW
- [frontend/src/pages/ReachyRadioPage.tsx](frontend/src/pages/ReachyRadioPage.tsx) — NEW
- [frontend/src/hooks/useReachyVoiceConfig.ts](frontend/src/hooks/useReachyVoiceConfig.ts) — NEW
- [frontend/src/App.tsx](frontend/src/App.tsx) — two new routes
- Sidebar component — two new entries

## Reused infrastructure (no new abstractions)

- `LlmRouter.set_task_model` / `resolve_provider_model` — already there.
- `unified_llm_client.chat()` — already returns provider+model.
- `JsonStorage` utility — already persists `workspace/llm/router_config.json`; we add `workspace/reachy/voice_config.json` the same way.
- React Query + Zustand patterns from existing `useReachyApi` hooks.
- Existing `/api/audio/models`, `/api/llm/available-models`, `/api/reachy/realtime/config` — already live.

## Verification

End-to-end checks on the live stack:

1. Rebuild and restart containers:
   - `docker compose -f docker-compose.sprint.yml build --no-cache zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api`
   - `docker compose -f docker-compose.sprint.yml build --no-cache zero-ui && docker compose -f docker-compose.sprint.yml up -d zero-ui`
   - Restart host_agent (`cd host_agent && .venv\Scripts\python main.py` or its launcher).
2. First voice turn after restart completes in < 5 s with no fallback; badges show `stt ~2s · faster-whisper/tiny`, `llm … · kimi/…`, `tts … · piper/lessac-medium`.
3. Visit `/reachy`, open the gear drawer, switch STT to `small` → next turn badge reflects new model; latency rises modestly but no fallback fires.
4. Switch LLM dropdown to a different provider/model → verify `GET /api/llm/resolve/voice_reply` returns it; next voice turn badge shows it.
5. Switch TTS voice → next turn's audio uses the new voice; badge shows it.
6. Visit `/reachy/voice-settings` — full page shows active stack, recent voice-turn history, all three dropdowns.
7. Visit `/reachy/radio` — Start / Stop / Analyze buttons round-trip to the backend without errors.
8. Force a real failure (e.g., kill host_agent mid-turn) → fallback still fires and surfaces as an error badge with `ok: false`, not a silent hang.
9. Backend unit check: `curl http://localhost:18792/api/reachy/voice/config` returns valid JSON; `PUT` with bad model name returns 400, not 500.
