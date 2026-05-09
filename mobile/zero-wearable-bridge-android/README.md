# Zero Wearable Bridge — Android

Companion app that streams Meta Ray-Ban glasses → Zero. Written in Kotlin
using the official Meta Wearables Device Access Toolkit (DAT) SDK.

## What it does

1. Pairs with Meta Ray-Ban / Oakley Meta glasses via the DAT SDK.
2. Subscribes to the glasses' **camera** (~1 fps JPEG) and **microphone**
   (5-mic array PCM16).
3. Forwards each JPEG to `POST /api/sight/meta_rayban/ingest` on your
   Zero backend.
4. Forwards audio chunks to `POST /api/sight/meta_rayban/audio-chunk`.
5. Opens a WebSocket to `/api/sight/meta_rayban/notify` so Zero can
   push TTS / text back to the glasses open-ear speaker.
6. Shows a persistent foreground notification, a quick-tile "Pause Zero"
   shortcut, and privacy toggles (mic-only, vision-only, home Wi-Fi only,
   battery saver).

## Prerequisites

- Android Studio Hedgehog (2025.1) or newer.
- Kotlin 1.9+, JDK 17.
- Meta Wearables DAT SDK — apply at
  <https://developers.meta.com/wearables/> for developer preview access.
  Once approved, drop the DAT AAR into `app/libs/` or wire its Maven
  artifact.
- A paired Meta Ray-Ban Gen 2, Oakley Meta HSTN, or Ray-Ban Meta Display.

## Configuration

Create `app/src/main/assets/zero.properties`:

```properties
# Where your Zero backend lives. Tailscale / LAN works great.
zero.api.url=https://zero.your-tailnet.ts.net
# Bearer token — same as ZERO_GATEWAY_TOKEN in c:\code\zero\.env
zero.api.token=REDACTED
# Provider id on the Zero side; leave as `meta_rayban` unless you renamed it.
zero.sight.provider=meta_rayban
```

Never commit a real token. Prefer a `local.properties` entry and inject
it via BuildConfig.

## Architecture

```
 ┌────────────┐   BLE + HFP   ┌──────────────┐   HTTPS    ┌───────────┐
 │ Ray-Ban    │──────────────▶│  Android App │───────────▶│ Zero API  │
 │ Meta       │   JPEG / PCM  │  DAT SDK     │  /ingest   │ /api/     │
 │  (camera,  │◀──────────────│  + OkHttp    │   /audio   │ sight/    │
 │   mic,     │   TTS audio   │  + Foreground│◀───WS──────│ meta_     │
 │   speaker) │               │  Service     │  /notify   │ rayban/*  │
 └────────────┘               └──────────────┘            └───────────┘
```

## Module layout (scaffolded)

- `app/src/main/java/com/zero/wearablebridge/MainActivity.kt`
  — Settings screen + pause/resume controls.
- `app/src/main/java/com/zero/wearablebridge/MainService.kt`
  — Foreground service that owns the DAT session + uplinks.
- `app/src/main/java/com/zero/wearablebridge/GlassesSession.kt`
  — Subscribes to DAT camera + mic + gesture events.
- `app/src/main/java/com/zero/wearablebridge/ZeroUplink.kt`
  — OkHttp client that POSTs to `/sight/{provider}/ingest`,
    `/audio-chunk`, and maintains the WebSocket `/notify` subscription.
- `app/src/main/java/com/zero/wearablebridge/NotificationSink.kt`
  — Renders inbound text as speech through glasses open-ear speaker
    via DAT's playback API.
- `app/src/main/java/com/zero/wearablebridge/PrivacyState.kt`
  — Hard kill switch + per-stream toggles + Wi-Fi gate.

## Privacy model (mandated)

- **Global kill switch** — single tap from notification drawer and
  quick-tile; immediately stops DAT subscriptions AND clears the local
  audio/frame ring buffers.
- **Visible indicator** — persistent foreground notification shows a
  red "Zero is watching" banner whenever a stream is active.
- **Wi-Fi gate** — default: stream only on your home SSID. Toggle in
  settings.
- **Battery saver** — below 30 % the app downshifts to "frame on
  gesture" (only sends a JPEG when the user tap-and-holds the capture
  button on the glasses).
- **Telemetry** — none. No analytics, no crashlytics by default.

## Building (once you have the DAT AAR)

```bash
./gradlew :app:assembleDebug
```

Install to a paired Android device:

```bash
./gradlew :app:installDebug
```

## Running end-to-end against Zero

1. Start `zero-api` and `host_agent` on your Windows host.
2. In Zero, `POST /api/sight/select` with `{"provider": "meta_rayban"}`
   to make the glasses the active sight source.
3. Launch this app, approve the runtime permissions, and start the
   foreground service.
4. Speak into the glasses mic or trigger a photo — you'll see frames
   arriving at Zero's `/api/sight/meta_rayban/frame.jpg` endpoint and
   show up in `ReachyCameraViewer` if you switch the UI to the glasses
   provider.

## Alternative hardware paths

If the Meta DAT SDK is still preview-locked when you're ready to build
this, the same `/sight/meta_rayban/ingest` endpoint works with anything
that can POST a JPEG:

- **Brilliant Labs Frame** — native Python SDK. A single-file Python
  pusher can run on the paired phone.
- **MentraOS (Even Realities G1, Vuzix, etc.)** — TypeScript SDK;
  swap the provider id to `mentra` and add a new SightProvider on the
  Zero side (10-line subclass of `MetaRayBanProvider`).
- **Your phone camera** — quickest MVP. Point any "IP webcam" app at
  `/api/sight/meta_rayban/ingest`.
