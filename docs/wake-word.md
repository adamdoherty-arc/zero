# Wake-word — "Hey Zero"

## Current state (2026-05-20)

The phrase the system actually fires on is **"hey jarvis"** — that's the
out-of-the-box openWakeWord model that ships with the upstream package. The
UI calls it **"Hey Zero"** because that's the product brand we're building
toward; the underlying model swap is queued as Legion sprint **Feature-18**.

Until the custom model lands, when you want to wake Reachy say "hey jarvis"
out loud. Everything downstream (silent-listen gate, response window,
notification fan-out) keys off the wake fire — it does not care what phrase
was used.

## Architecture

- `host_agent/openwakeword_loop.py` — runs the openWakeWord ONNX model on
  80 ms PCM frames from the Reachy mic. When the score crosses the threshold
  it records the user's follow-up utterance and hands the text to
  `_on_wake_command`.
- `host_agent/main.py:_on_wake_command` — fires a fire-and-forget POST to
  `/api/reachy/wake-word/fired` so the backend stamps `last_wake_at` BEFORE
  the user finishes speaking the command, then dispatches the command to
  `/api/reachy-intent/handle`.
- `backend/app/services/reachy_companion_service.py:mark_wake_fired` —
  stamps `policy.last_wake_at = now`. `extend_wake_window()` does the same
  thing from the per-TTS-chunk hot path without spamming the event log.
- `backend/app/services/reachy_realtime/local_handler.py:_speak_chunk` —
  checks `action_allowed("speak")` before synthesizing. Inside the wake
  window it also calls `extend_wake_window()` so a long answer doesn't get
  cut mid-sentence.

## Configuration

| env var | default | purpose |
| --- | --- | --- |
| `ZERO_WAKE_MODE` | `auto` | `auto` / `openwakeword` / `porcupine` / `whisper` / `off` |
| `ZERO_OWW_MODEL_PATH` | unset | absolute path to a custom `.onnx` model (used by Feature-18) |
| `ZERO_OWW_KEYWORD` | `hey_jarvis` | model key inside the OWW prediction buffer |
| `ZERO_OWW_THRESHOLD` | `0.5` | fire when score crosses this value |
| `ZERO_OWW_COOLDOWN_S` | `2.0` | cooldown to avoid re-firing on the same utterance |
| `ZERO_PICOVOICE_ACCESS_KEY` | unset | unlocks Porcupine fallback if openWakeWord isn't available |

`CompanionPolicy.wake_response_window_s` (default `30`) controls how long
after a wake fire Reachy is allowed to speak. The window auto-extends on
each TTS chunk while inside it.

## Sprint roadmap

- **Feature-17** (queued): bridge phase — sweep the UI copy so "Hey Zero"
  shows everywhere even though the underlying model is still `hey_jarvis`.
- **Feature-18** (queued): train custom openWakeWord model for "Hey Zero".
  Tools live at `tools/wake_word_training/`:
  - `generate_samples.py` — synthesize ~2,000 positive samples via Piper
    TTS with multi-voice + pitch/noise perturbation.
  - `fetch_negatives.py` — pull negatives from common-voice + ambient
    background noise.
  - `train.py` — run the upstream training recipe, export to
    `host_agent/models/wake/hey_zero.onnx`.
  - Cutover: set `ZERO_OWW_MODEL_PATH` to the new file and update
    `wake_presence_service` defaults. Target: 95 % recall on a held-out
    test set, ≤ 1 false positive per hour ambient.

## Tuning ideas (not yet sprinted)

- Diarize the meeting audio first and only run wake detection on the
  user's own voice channel — eliminates the "meeting attendee said
  'jarvis'" false-positive class.
- Add a confirm beep (subtle ack tone via Reachy speaker) so the user
  knows the window is open before they start the question.
- Per-persona cooldowns: when a long response is mid-stream, ignore
  re-fires for the duration so the model doesn't pre-empt itself.
