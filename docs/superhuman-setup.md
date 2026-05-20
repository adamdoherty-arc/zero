# Superhuman v2 — Zero as a virtual Zoom attendee

## What this is

Zero joins a Zoom (or Google Meet / Teams) meeting URL as a participant,
captures audio + transcript, can speak as an attendee, and exits when the
meeting ends. Implemented by `backend/app/services/meeting_agent_service.py`
which drives a headless Playwright Chromium tab.

This is gated by two env vars and disabled by default:

```
ZERO_MEETING_AGENT_ENABLED=true
ZERO_MEETING_AGENT_REAL_DRIVER=true
```

Without `REAL_DRIVER=true` the service runs in stub mode — sessions are
created, but the browser never actually opens. That's intentional: the
real driver needs Windows-host audio routing that the Docker container
can't provide on its own.

## One-time host setup (Windows)

### 1. Install VB-Audio CABLE (virtual mic)

Free download: https://vb-audio.com/Cable/

After install, Windows gets a new playback device "CABLE Input" and a
new recording device "CABLE Output". Zero pipes its TTS audio into
"CABLE Input"; Zoom's headless Chromium picks it up via "CABLE Output"
as if it were a regular microphone.

```powershell
# Confirm both devices exist
Get-CimInstance Win32_SoundDevice | Select-Object Name, Status
```

### 2. Install pyvirtualcam (avatar tile)

```powershell
pip install pyvirtualcam
```

`pyvirtualcam` exposes a virtual webcam that any meeting client can
select. Zero renders a static PNG (the Zero mascot) into it so Reachy
shows up as a video tile, not a black square.

### 3. Install Playwright Chromium

Already installed inside the zero-api container if you bring up
the meeting-agent stack:

```bash
docker exec zero-api playwright install chromium
```

If you ever rebuild the image, the install survives because it's
declared in `backend/requirements.txt`.

### 4. Flip the env vars

In `c:/code/zero/.env`:

```
ZERO_MEETING_AGENT_ENABLED=true
ZERO_MEETING_AGENT_REAL_DRIVER=true
ZERO_MEETING_AGENT_VIRTUAL_MIC="CABLE Input"
ZERO_MEETING_AGENT_VIRTUAL_CAM="OBS Virtual Camera"
```

Then `docker compose -f docker-compose.sprint.yml up -d zero-api` to
reload.

## How to send Zero to a meeting

### From the UI

`/meetings` → click "Send Zero" on any upcoming calendar event whose
description contains a Zoom/Meet/Teams URL.

### From the API

```bash
curl -X POST http://localhost:18792/api/meetings/{meeting_id}/send-zero
```

The scheduler's auto-record job will spawn a meeting-agent session at
the event start time instead of doing local loopback capture. Zero
joins as participant "Zero" with the configured avatar tile. Transcript
streams to `/api/meeting-agent/sessions/{id}/notes` and lands in the
vault on stop.

## Per-event opt-in (preferred default)

Don't ship Zero to every meeting by default — many will be in-person or
loopback-friendly. The scheduler reads
`workspace/meetings/superhuman_optin.json` for per-event flags. The
"Send Zero" UI button writes there.

## What's still stubbed

- Avatar tile is a static PNG. Lip-sync via visemes from the existing
  `reachy_realtime/visemes.py` is queued as a follow-on.
- Zoom-specific captcha / waiting-room handling is best-effort.
- TLS interception for end-to-end captioned-audio capture is not done;
  we rely on the audio actually playing through "CABLE Output".

## Why not Recall.ai or Vexa?

- **Recall.ai** is a paid SaaS that does this with one HTTP call and a
  webhook. We could swap to it if self-hosting becomes painful. The
  meeting-agent service already speaks Recall's mental model (join /
  speak / ingest / leave) so swapping it in is a 1-day port.
- **Vexa** is an open-source equivalent. Heavier to operate (full
  Kubernetes stack with bot pool) but no vendor lock-in.

Per the user's reuse-first culture (`c:/code/zero/.claude/rules/20-git-
workflow.md`) — if our self-hosted Playwright path stays under 200
lines of code and 90 % reliable, we stay there. Past that, swap.

## Sprint roadmap

- **Feature-19** (queued): unstub the real driver, ship the VB-Cable +
  pyvirtualcam runtime, expose `/api/meetings/{id}/send-zero`, add the
  Meetings UI button, write live transcript notes endpoint.
- **Enhancement-08** items: visemes-driven avatar, Recall.ai adapter
  behind an env flag, captcha-aware retry, per-attendee diarization.
