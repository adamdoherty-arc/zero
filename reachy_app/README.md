# reachy_mini_zero

Installable Reachy Mini app that turns the robot into a client of the
[Zero](../) chief-of-staff backend.

- Reachy captures audio → POSTs it to Zero's `/api/reachy/voice`
- Zero runs persona-aware LLM + TTS + the 100-clip motion library
- Reachy plays back the synthesized audio and fires the gesture actions
  Zero returned

All language, personality, motion-library lookup, and pomodoro / meeting
state live on Zero. The robot is just I/O.

## Install on the Reachy Mini

From the Reachy Mini Desktop App's dashboard:

1. **App Store → Install from URL**
2. Paste `https://github.com/<your-fork>/zero/tree/main/reachy_app`
3. Configure environment variables in the app's settings pane:
   - `ZERO_API_URL` — where Zero is running (default
     `http://host.docker.internal:18792` if you run Zero on the same
     machine, otherwise your LAN IP).
   - `ZERO_GATEWAY_TOKEN` — from Zero's `.env`
     (`ZERO_GATEWAY_TOKEN=...`).
   - `ZERO_CHUNK_SECONDS` — how many seconds of audio to capture per
     turn. Default `5`.

## Install in dev mode (local SDK)

```bash
cd reachy_app
pip install -e .
reachy-mini run reachy_mini_zero
```

## How it talks to Zero

Every `ZERO_CHUNK_SECONDS`:

```
Reachy mic  ──  WAV (int16 mono, 16 kHz)
             │
             ▼
  POST {ZERO_API_URL}/api/reachy/voice
   multipart audio file
             │
             ▼
  Zero: STT → persona-wrapped LLM → strip gesture markers → TTS
             │
             ▼
  { transcription, llm_response, audio_response_b64, gesture_actions }
             │
             ▼
  Reachy   ──  play audio + fire [emotion:..] [dance:..] [look:x,y,z]
```

Gestures are fired on the *local* SDK (not back over HTTP) for snappiness.

## Scope of this scaffold

Implemented:
- 5 s windowed audio capture + WAV upload
- Gesture action dispatch via local SDK helpers
- Configuration via environment variables

Left as TODOs for a downstream author:
- Voice Activity Detection (currently records fixed-length chunks).
- Wake-word ("hey reachy") — plug in Picovoice or
  [fcollonval/reachy_mini_wake_word](https://huggingface.co/spaces/fcollonval/reachy_mini_wake_word).
- Push-to-talk UI via `custom_app_url` Gradio pane.
- Bidirectional streaming (OpenAI Realtime-style) when Zero grows that endpoint.
