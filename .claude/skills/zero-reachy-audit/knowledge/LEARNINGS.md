# Reachy Audit Learnings

Pattern log. Each entry: date, dimension, symptom, hypothesis, status (`[WATCH]` / `[PROMOTED]` / `[DEMOTED]` / `[RESOLVED]`). Promoted patterns migrate to SCORING_RUBRIC.md as checkable rules on the next audit. Demoted patterns get flagged for architectural review.

## 2026-04-22 — Seed run (from harvest session)

### [RESOLVED] Daemon dataset path needs org prefix
- **Dimension**: Motion & Body
- **Symptom**: All `/emotion` and `/dance` calls 404'd against daemon v1.6.4 with HF saying `Repository Not Found for url: huggingface.co/api/datasets/reachy-mini-emotions-library/revision/main`.
- **Root cause**: Daemon path is `/api/move/play/recorded-move-dataset/{org}/{repo}/{move_name}` — three path components. Zero was passing just `reachy-mini-emotions-library`, so the daemon prepended its own URL scheme and tried to resolve a bare HF id.
- **Fix**: Pin `EMOTIONS_DATASET = "pollen-robotics/reachy-mini-emotions-library"` and keep legacy bare-name fallbacks.
- **Commit**: `caf89be`
- **Status**: RESOLVED. Watch for breakage if Pollen rehomes the dataset.

### [RESOLVED] Voice-loop LLM fallback called non-existent router method
- **Dimension**: Voice & Conversation
- **Symptom**: Every voice turn returned the canned "I'm sorry, I had trouble processing that."
- **Root cause**: `LlmRouter` is a *resolver*, not a chat caller. It has no `.chat()` method. The fallback path crashed with `'LlmRouter' object has no attribute 'chat'`.
- **Fix**: Route through `unified_llm_client.chat(prompt=..., system=..., task_type='voice_reply')`.
- **Commit**: `9a01e35`
- **Status**: RESOLVED. Live-verified with pizza-joke end-to-end.

### [WATCH] Desktop app crashes on lazy dataset download
- **Dimension**: Motion & Body
- **Symptom**: First `/dance` call made the Pollen Tauri desktop app unresponsive; port 8000 refused connections; required manual restart.
- **Hypothesis**: Daemon tries to fetch the dances library on first play and a hang or exception kills the Tauri process.
- **Mitigation**: `host_agent/run_reachy_daemon.py` with `preload_datasets=True` launches the same FastAPI sidecar headless, pre-downloading all datasets on startup. Users who don't use it should open the desktop app, wait for "libraries synced", then test.
- **Status**: WATCH. If seen again with the headless launcher, promote to fix.

### [WATCH] MediaPipe wheel lacks `mp.solutions` on some indexes
- **Dimension**: Environment & Integrations
- **Symptom**: `mediapipe==0.10.33` installed via `pip` but `hasattr(mp, 'solutions')` was False; `_detect_hands` 500'd with "module 'mediapipe' has no attribute 'solutions'".
- **Root cause**: Some newer wheels (arm / stripped-down builds) ship only the `tasks` submodule.
- **Fix**: Pin `mediapipe>=0.10.11,<0.10.20` which still has the legacy namespace. Fallback import path added.
- **Status**: WATCH. If pin stops being available, migrate to the `mediapipe.tasks.vision.HandLandmarker` API.

### [WATCH] Routes shadowed by dynamic path parameters
- **Dimension**: cross-cutting (FastAPI)
- **Symptom**: `GET /personas/stats` returned "unknown persona: stats" because `/personas/{persona_id}` matched first.
- **Fix**: Declare concrete routes *before* dynamic-param catch-alls in the router file.
- **Status**: WATCH — any new `/personas/xxx` or `/moves/user/xxx` route must go above its `/{...}` sibling.

### [WATCH] Rebuild misses in-flight edits
- **Dimension**: cross-cutting (deploy)
- **Symptom**: Second rebuild returned 404s for `/radio/*` and `/context/*` because the first `docker compose build` started before those files existed; image was stale.
- **Fix**: Always finish edits *then* rebuild. When chaining agents, fence the edits → build with a single synchronous block.
- **Status**: WATCH, with a playbook note.

### [WATCH] Gesture dispatched after TTS finishes
- **Dimension**: Persona & Emotion
- **Symptom**: Emotion played *after* the reply was fully spoken; robot looked delayed.
- **Hypothesis**: `parse_and_strip()` runs before `say()` but gestures dispatch sequentially via `asyncio.create_task(self._dispatch_gestures(actions))` which itself awaits each gesture. If the daemon's emotion playback is longer than the first TTS word, the gesture lags.
- **Proposed fix**: Dispatch each gesture at its `offset` in the clean_text using a best-guess character-per-millisecond rate, or split TTS into chunks keyed to offsets.
- **Status**: WATCH. Not yet live-measured — needs an audit tick where we time it.

## Seeded anti-patterns (from SKILL.md Common Dimension Anti-Patterns)

These came with the skill definition and stay `[WATCH]` until observed.

| Anti-pattern | Dimension | Detection | Fix direction | Status |
|---|---|---|---|---|
| Wake word off-thread blocks main loop | Voice | `wake_loop.py` CPU > 50% single-core | Move to subprocess w/ ring buffer | [WATCH] |
| DoA angle drifts when antennas move | Meeting | DoA reading + antenna position correlated | Require daemon ≥ 1.6.4 | [WATCH] — we're on 1.6.4 |
| Presence beat runs while daemon offline | Presence | 404s from daemon on every beat | Gate with `is_connected()` before dispatch | [WATCH] — mitigation in place |
| HA watcher eats API quota | Environment | Poll interval too aggressive | Respect `ZERO_HA_POLL_SECONDS`, back off on 429 | [WATCH] |
| Motion library clip plays but aliasing fails | Motion | LLM emits `[emotion:happy]`, daemon 404 | Alias resolver fallback chain | [RESOLVED] — live-verified |

## How to use this file

When the audit hits a symptom, look here first. If it matches:
- `[WATCH]` — log a new occurrence below the entry (bullet `- 2026-04-22: seen in…`). After 2 occurrences with a reliable fix, promote.
- `[PROMOTED]` — the rule moved to `SCORING_RUBRIC.md` as a gradable deduction. Leave the entry here for history.
- `[DEMOTED]` — the fix failed repeatedly. Flag for arch review, stop auto-applying.
- `[RESOLVED]` — historical record, no new occurrences expected.
