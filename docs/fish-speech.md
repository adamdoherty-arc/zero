# Fish-Speech voice for Reachy

Fish-Speech S2 Pro (March 2026, Apache 2.0) is the recommended local TTS for warm/expressive voices. It supports zero-shot voice cloning from a 10-15 second reference clip and streams audio at ~200 ms TTFB on a single consumer GPU.

Zero's TTS service routes any voice id starting with `fish:` to a Fish-Speech server at `host.docker.internal:18802` (configurable via `FISH_SPEECH_URL`). Everything else falls through to Piper / Edge-TTS, so this is purely additive — the realtime loop never breaks if Fish-Speech is offline.

## Launch

Repo: https://github.com/fishaudio/fish-speech

```powershell
# Install once
pip install fish-speech

# Serve OpenAI-compatible /v1/audio/speech on the host.
fish-speech serve --port 18802 --device cuda
```

Verify:

```powershell
curl http://localhost:18802/v1/models
```

## Voice cloning

1. Record a 10-30 second sample of the target voice (clean, consistent tone).
2. Upload via Zero's API:

```powershell
$bytes = [Convert]::ToBase64String([IO.File]::ReadAllBytes("warm-female.wav"))
$body = @{ voice_id = "warm-female"; audio_b64 = $bytes } | ConvertTo-Json
Invoke-RestMethod -Method POST -Uri "http://localhost:18792/api/reachy/realtime/voices/clone" `
  -ContentType application/json -Body $body
```

Zero stores the file at `backend/app/data/voice_clones/warm-female.wav`. The voice is now selectable as `fish:warm-female` in any persona's `voice.txt` or in the unified settings modal's voice picker.

## Companion girlfriend default

The shipped persona `companion_girlfriend` ships with `voice.txt = en-US-JennyNeural` (Edge-TTS) so it works out of the box without Fish-Speech running. To upgrade, drop in a cloned voice:

```
# backend/app/data/reachy_profiles/companion_girlfriend/voice.txt
fish:warm-female
```

Restart `zero-api` so the profile cache picks it up, or wait for the next session start (the cache reload triggers on persona changes).

## Consent

Voice cloning works on any audio. **Don't clone real people without their consent** — the sample is stored on disk and used to drive whatever the persona's system prompt says. For first-run testing, use:

- Your own voice
- A LibriVox public-domain audiobook reader
- A synthetic baseline voice from another TTS

## Fallback chain

When the user picks `fish:<id>`:

1. POST `/v1/audio/speech` to `FISH_SPEECH_URL`. If that returns 200, use the WAV bytes.
2. On any failure (server down, model not loaded, voice id not found): fall back to Edge-TTS with the bare voice id (which probably won't match — but at least the loop produces audio and surfaces an error transcript).
3. The local handler now emits a structured error transcript event when TTS returns empty audio, so the user sees the failure instead of a silent robot.
