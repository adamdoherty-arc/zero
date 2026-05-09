# Zero + Reachy + Meta Ray-Ban — Shared Sight Integration Plan

## Context

You own Meta Ray-Ban glasses and want them to become a shared sensor for **Zero** (your 24/7 chief-of-staff assistant) and **Reachy Mini** (your embodied desk employee). You also want a "what Reachy sees" panel in the Zero UI — which today is broken. This plan delivers both as one coherent pipeline: a pluggable "Sight" provider layer that Reachy camera, a Windows webcam, and the Meta glasses all feed into, then Zero reacts to what it sees.

### Current broken state (verified)

- [reachy_service.py:580-606](backend/app/services/reachy_service.py#L580-L606) — `get_stream_url()` returns `https://<host>:8443/webrtc`. That URL was served by the old Tauri desktop app and died in commit `cf06530 feat(reachy): headless daemon launcher replaces Tauri desktop app`. It is a zombie endpoint.
- [reachy_service.py:595-606](backend/app/services/reachy_service.py#L595-L606) — `capture_image()` returns `b""` with a comment acknowledging the daemon exposes only `/api/camera/specs`.
- [reachy.py:597-610](backend/app/routers/reachy.py#L597-L610) — Zero still exposes `/reachy/camera/stream`, which dutifully returns the dead URL.
- [ReachyTeleopPage.tsx:175-189](frontend/src/pages/ReachyTeleopPage.tsx#L175-L189) — renders the URL as a hyperlink; no video is embedded anywhere in the app.
- Reachy SDK daemon's camera router ([C:\code\reachy-apps\sdk\reachy_mini\src\reachy_mini\daemon\app\routers\camera.py](C:\code\reachy-apps\sdk\reachy_mini\src\reachy_mini\daemon\app\routers\camera.py)) exposes `/api/camera/specs` only — no frame endpoint.
- The SDK **does** ship a full camera stack ([camera_base.py](C:\code\reachy-apps\sdk\reachy_mini\src\reachy_mini\media\camera_base.py), `camera_gstreamer.py`) and community apps (e.g., `reachy_alarm_clock\src\reachy_alarm_clock\camera_worker.py`) show the reuse pattern — a thread-safe ring buffer polled at 30 Hz. We can lift this into the `host_agent` running on the Windows host (port 18794).

### Meta DAT SDK reality (April 2026)

- Public **developer preview**: [meta-wearables-dat-android](https://github.com/facebook/meta-wearables-dat-android) and `-ios`.
- Exposes ~1 fps JPEG, 5-mic audio, open-ear speaker, notification push, agent invocation.
- **Mandatory mobile proxy** — glasses → paired phone → your backend. No direct Wi-Fi path to Windows.
- Reference pattern: [VisionClaw](https://github.com/Intent-Lab/VisionClaw) (DAT + Gemini Live + OpenClaw).
- Open-source fallbacks if DAT regresses: [Brilliant Labs Frame](https://brilliant.xyz/products/frame) (~$349, Python SDK, direct Wi-Fi) or [MentraOS](https://github.com/Mentra-Community/MentraOS) (MIT, multi-device).

---

## Phase 1 — Fix "what Reachy sees" in Zero UI

**Goal:** live MJPEG from Reachy's own camera visible in Zero within a day. Nothing external, pure plumbing.

### Create

- `host_agent/routes/camera.py` (on the Windows host, port 18794):
  - `GET /camera/mjpeg` → `multipart/x-mixed-replace` JPEG stream at ~15 fps.
  - `GET /camera/frame.jpg` → single JPEG (latest frame, for VLM analysis).
  - `GET /camera/status` → `{active, fps, backend, resolution, locked_by}`.
  - Backed by a `CameraWorker` thread that uses `reachy_mini.media.camera_gstreamer.GStreamerCamera` (SDK-native) with `cv2.VideoCapture(0)` as a fallback.
- [backend/app/routers/sight.py](backend/app/routers/sight.py) (new) — Zero-side proxy. Uses `httpx.AsyncClient.stream()` to forward bytes with zero buffering.
- [frontend/src/components/reachy/ReachyCameraViewer.tsx](frontend/src/components/reachy/ReachyCameraViewer.tsx) (new) — `<img src={apiUrl('/reachy/camera/mjpeg')}>` with connection indicator, freeze button, and a "snapshot → analyze" action that POSTs to `/reachy/vision/detect`.

### Modify

- [reachy_service.py:580-606](backend/app/services/reachy_service.py#L580-L606) — `get_stream_url()` returns the new Zero-relative MJPEG path; `capture_image()` pulls `/camera/frame.jpg` from the host_agent.
- [reachy.py:597-611](backend/app/routers/reachy.py#L597-L611) — `/reachy/camera/stream` returns the fixed URL; add `GET /reachy/camera/mjpeg` and `GET /reachy/camera/capture` that stream-proxy the host_agent.
- [ReachyTeleopPage.tsx:175-189](frontend/src/pages/ReachyTeleopPage.tsx#L175-L189) — replace the hyperlink card with `<ReachyCameraViewer />`.
- Add `<ReachyCameraViewer />` to [ReachyMeetingsPage.tsx](frontend/src/pages/ReachyMeetingsPage.tsx) and a new Dashboard card.

### Deps

- `opencv-python` in host_agent venv (Zero already has it).

### Effort

~1 day. ~60% on the host_agent side, ~40% on Zero proxy + UI.

---

## Phase 2 — Wearable-agnostic `SightProvider` layer

**Goal:** one abstraction that Reachy's camera, a USB webcam, and the Meta glasses (pushed from mobile) all satisfy. This is the linchpin for the rest of the plan — it means Meta glasses support is a new file, not a refactor.

### Create

- `backend/app/services/sight/base.py`:
  ```python
  class SightProvider(ABC):
      name: str
      async def status(self) -> dict
      async def get_latest_frame(self) -> bytes | None        # JPEG
      async def mjpeg_stream(self) -> AsyncIterator[bytes]
      async def subscribe_audio(self) -> AsyncIterator[bytes] # PCM16
      async def push_notification(self, text: str) -> bool
      async def ingest_frame(self, jpeg: bytes) -> None       # for pushed providers
  ```
- `backend/app/services/sight/reachy_provider.py` — wraps Phase 1 endpoints.
- `backend/app/services/sight/webcam_provider.py` — OpenCV on host for any USB cam (fills gap before Android app lands).
- `backend/app/services/sight/meta_rayban_provider.py` — pure push buffer. Ring-buffer of 30 frames + last 60 s of audio. `ingest_frame()` appends; `get_latest_frame()` returns most recent.
- `backend/app/services/sight/registry.py` — `get_active_provider()`, `list_providers()`, user-selectable active provider stored in settings.
- [backend/app/routers/sight.py](backend/app/routers/sight.py) (promote from Phase 1 stub):
  ```
  GET  /sight/providers                list + status
  GET  /sight/{id}/frame.jpg           latest JPEG
  GET  /sight/{id}/mjpeg               live stream (if supported)
  POST /sight/{id}/ingest              multipart/form-data, from mobile bridge
  POST /sight/{id}/audio-chunk         base64 pcm16 + timestamp
  WS   /sight/{id}/notify              outbound text/audio to wearable
  POST /sight/select                   set active provider
  ```

### Modify

- [reachy_vision_service.py](backend/app/services/reachy_vision_service.py) — add `analyze_latest()` that pulls from `registry.get_active_provider().get_latest_frame()` instead of only accepting uploaded images.

### Reuse

- `meeting_audio_buffer.py` already has a thread-safe ring buffer pattern; crib it.

### Effort

~1.5 days.

---

## Phase 3 — Meta DAT Android companion app

**Goal:** real glasses → Zero. Kept isolated so it can slip without blocking the rest of the plan.

### Create

`mobile/zero-wearable-bridge-android/` (Kotlin, Android Studio project):

- `MainService.kt` — foreground service, persistent notification, "Zero is watching" indicator.
- `GlassesSession.kt` — opens DAT session, subscribes to 1 fps JPEG + mic audio, receives tap/voice events.
- `ZeroUplink.kt` — OkHttp client. POSTs to `https://<host-on-tailscale-or-lan>:18792/api/sight/meta_rayban/ingest` with bearer `ZERO_GATEWAY_TOKEN`. WebSocket to `/api/sight/meta_rayban/notify` to receive TTS to speak through glasses.
- `SettingsActivity.kt` — endpoint URL, token, privacy toggles: **Pause Zero** (hard off), **Mic only**, **Vision only**, **Home Wi-Fi only**, **Battery saver downshifts to frame-on-gesture**.
- Quick-tile "Pause Zero" shortcut so it's one tap from the lock screen.

### Deps

- `com.meta.wearables.dat` (preview SDK).
- OkHttp 4.x, Kotlin coroutines.

### Effort

~1 week. Longest external dependency; build in parallel with Phases 5–6.

---

## Phase 4 — Local VLM for ambient understanding

**Goal:** frames → structured scene description + OCR, without sending every frame to a cloud API. Uses your existing **vLLM + shared LiteLLM router** at `host.docker.internal:4444` — no Ollama required.

### Create

- `backend/app/services/vision_vlm_service.py`:
  ```python
  async def describe_scene(jpeg: bytes, prompt: str = DEFAULT) -> dict
  async def answer_about_scene(jpeg: bytes, question: str) -> str
  async def tag_objects(jpeg: bytes) -> list[str]
  ```
  Posts OpenAI-format vision chat-completion to the LiteLLM router:
  ```json
  {
    "model": "qwen3-vl",
    "messages": [{"role": "user", "content": [
      {"type": "text", "text": "..."},
      {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
    ]}]
  }
  ```

### Modify

- [llm_router.py](backend/app/infrastructure/llm_router.py) — add a `vision` task-type profile pointing at the user's vLLM-hosted Qwen3-VL via the shared LiteLLM router (`ZERO_LITELLM_URL`, default `http://host.docker.internal:4444/v1`). Model name configurable via `ZERO_VLM_MODEL` (default `qwen3-vl`).
- [reachy_vision_service.py](backend/app/services/reachy_vision_service.py) — add `analyze_scene(jpeg)` that fuses MediaPipe face/hand output with the VLM description into one dict.
- [reachy.py](backend/app/routers/reachy.py) — `POST /reachy/vision/scene` returning detections + VLM caption.

### Deps

None — piggybacks on your existing vLLM + shared LiteLLM router. You manage the model version outside Zero.

### Effort

~0.5 day.

---

## Phase 5 — Zero reacts to what the user sees

**Goal:** the loop is closed. Zero narrates the day, Reachy answers "what do you see", actionable moments become tasks.

### Modify

- [scheduler_service.py](backend/app/services/scheduler_service.py) — register `ambient_vision_tick` alongside the existing `autonomous_research_tick`. 30 s cadence. Flow:
  1. `active = registry.get_active_provider()`
  2. `jpeg = await active.get_latest_frame()` (skip if none or >60s stale)
  3. `scene = await vision_vlm_service.describe_scene(jpeg, AMBIENT_PROMPT)`
  4. If `scene.actionable` → push to agent approval queue, log to vault `/vault/00_Meta/_agent/vision/{YYYY-MM-DD}/{HH-MM}.md`.
  5. Emit `sight_observation` metric for the weekly digest.
  6. Backpressure: skip tick if previous VLM call still running (`asyncio.Lock`).
- [voice_loop_service.py](backend/app/services/voice_loop_service.py) — extend the persona-prompt assembler to prepend `"You can see: {scene.caption}"` when a `SightProvider` is active and the frame is <15 s old.
- [reachy_context_service.py:58](backend/app/services/reachy_context_service.py#L58) — `build_context_hint()` gains a `sight_context` block.
- [reachy_emotion_parser.py](backend/app/services/reachy_emotion_parser.py) — register `[observe]` marker. Implementation piggybacks on the existing `[look]` animation so Reachy visibly "pays attention" during a VLM call.
- [reachy_chat_provider.py](backend/app/services/reachy_chat_provider.py) — when the user asks "what do you see?", intercept and route to `active.get_latest_frame() + describe_scene()` instead of hallucinating.

### Effort

~1.5 days. Tasteful vault entries (dedup, not spammy) is most of it.

---

## Phase 6 — MCP + SecondBrain wiring

**Goal:** the glasses feed becomes first-class context in Claude Desktop and the weekly digest.

### Modify

- [zero_api_mcp.py](mcp_servers/zero_api_mcp.py) — add to `TOOLS` and dispatcher:
  - `get_sight_frame(provider: str | None = None)` → base64 JPEG.
  - `describe_scene(provider: str | None = None, question: str | None = None)` → VLM answer.
  - `recent_sight_observations(hours: int = 24)` → pulls vault entries from Phase 5.
  - `list_sight_providers()` → registry state.
- [briefing_service.py](backend/app/services/briefing_service.py) — morning digest includes "What you saw yesterday" section pulling from the vault folder.

### Effort

~0.5 day.

---

## Phase 7 — Reachy ↔ Glasses cross-awareness

**Goal:** when both cameras are live, each informs the other. This is the "magic" phase — skip until Phases 1–6 land.

### Modify

- [reachy_context_service.py:58](backend/app/services/reachy_context_service.py#L58) — when Reachy camera AND glasses are both active, combine Reachy's DoA + face detection ("user 1m away, facing left") with glasses VLM ("user is looking at laptop showing VSCode") into one sentence for the persona prompt.
- [reachy_presence_service.py](backend/app/services/reachy_presence_service.py) — `user_attention_state()` returns `{"with_reachy" | "at_screen" | "moving" | "away"}` and drives idle animations (nap if away, lean-in if user glances at Reachy).

### Effort

~1 day.

---

## Ways to use all of these together (the "24/7 employee" scenarios)

These are the use cases that justify the whole build — each exercises glasses + Reachy + SecondBrain as one unit.

1. **Morning walk-and-brief.** Put glasses on over coffee. Zero reads overnight emails + today's calendar through the open-ear speaker. When you glance at your laptop showing the calendar, VLM notices and cross-references: *"I see you're looking at the 10am block — that conflicts with the gym slot you wanted."* Reachy, on your desk, plays its morning greeting gesture when you sit down.
2. **Ambient task capture.** Walk past a whiteboard, a sticky note, a receipt — Qwen2.5-VL OCRs it, drafts a task, drops it in the agent approval queue. One tap in the UI (or a voice confirm to Reachy) to accept.
3. **Meeting mode (in-person).** Real-world meeting, not Zoom. Glasses audio + video feed the existing `meeting_transcription_service`. VLM notes whiteboard content and who's in frame. Reachy stays quiet on your desk but the vault gets a full transcript + visual notes.
4. **Walking errand capture.** "Hey Zero, log this mug — sold out in Brooklyn." VLM OCRs the shelf tag + price. Filed as a price-watch task with a photo receipt in the vault.
5. **Focus enforcement.** Pomodoro running. VLM detects 8 minutes on Reddit through the glasses feed. Reachy turns to face you, plays a concerned emotion, says out loud *"you wanted to be on the invoice right now."* Glasses speaker repeats the same nudge if you're not at the desk.
6. **"Reachy, is the knob tight?"** Reachy rotates, captures its own frame, VLM answers. The glasses show you the same view (via the mobile notify channel) so you can confirm.
7. **Hands-busy kitchen assistant.** Cooking, hands covered — glasses see the recipe on your laptop AND the pan. Zero times steps via voice; Reachy acts as the confirmation nod ("yes, onions are browned").
8. **End-of-day narration.** Nightly digest rolls up `/vault/00_Meta/_agent/vision/{date}/` into a story: *"Today you spent 4h at your desk, saw Marius at 3pm, picked up the dry cleaning, and three receipts were filed."* Reachy reads the highlights out loud at 9pm.
9. **Persistent context for the LLM.** Every voice prompt to Reachy auto-prepends "You can see: X" (last VLM caption), so Reachy answers grounded questions without the user saying "look at this" — e.g., "what's that package on my desk?" just works.
10. **Second-pair-of-eyes debugging.** You're reading an error on your monitor; glasses VLM extracts the stack trace, sends it to Zero, Zero's `deep_research` subsystem starts a background investigation before you even ask.
11. **Silent assist via Ray-Ban Display.** If you have or upgrade to Ray-Ban Meta Display ($799, sEMG band), the notify WebSocket from Phase 2 can push text hints directly to the lens — silent, hands-free Zero.
12. **Robot learning from demos (research-mode).** If you qualify for Project Aria later, the same `SightProvider` slot can ingest egocentric video for Reachy policy training ([EgoZero pattern](https://spectrum.ieee.org/smart-glasses-robot-training): 20 min of demos → 70 % robot success on replicated tasks).

---

## Open decisions (recommendations in bold)

| Decision | Options | Recommendation |
|---|---|---|
| Mobile platform | iOS / **Android** | **Android** — DAT Android preview is ahead, matches your PWA-first setup |
| VLM model | **Qwen3-VL via existing vLLM** | **Qwen3-VL on your vLLM** via the shared LiteLLM router at `host.docker.internal:4444`. No Ollama. Model name configurable via `ZERO_VLM_MODEL`. |
| Hardware hedge | buy Frame / wait | **Wait** — Phase 2's provider abstraction makes a swap a single-file change. Revisit only if DAT is still unreliable after Phase 3 |
| Host_agent location | same repo as Zero / reachy-apps / private | Needs confirmation from you before Phase 1 — plan assumes host_agent is where you'll add `routes/camera.py` |
| Privacy model | per-provider toggle / global "eyes off" button | **Global kill switch** at top of nav, plus provider-level toggles. Hard stop ingest + purge ring buffer. Bright on-phone LED/haptic when streaming |

---

## Verification

**Phase 1**
- `curl -o /tmp/f.jpg http://localhost:18792/api/reachy/camera/frame.jpg && file /tmp/f.jpg` → *"JPEG image data"*.
- Browser → [http://localhost:5173/reachy/teleop](http://localhost:5173/reachy/teleop), new Camera card shows live feed.
- Wave hand: `curl -F file=@/tmp/f.jpg http://localhost:18792/api/reachy/vision/detect` returns hands array.

**Phase 2**
- `curl http://localhost:18792/api/sight/providers` → lists `reachy`, `webcam`, `meta_rayban`.
- Push then pull: `curl -F file=@test.jpg http://localhost:18792/api/sight/meta_rayban/ingest` then `curl -o got.jpg http://localhost:18792/api/sight/meta_rayban/frame.jpg` — bytes match.

**Phase 3**
- Android Studio debug build on phone (paired to glasses). Persistent notification shows "Zero Bridge streaming". Tail Zero logs for `sight_ingest` at ~1 Hz.
- Voice-trigger "Hey Meta, send to Zero" — frame appears in UI live.

**Phase 4**
- `curl -X POST -F file=@livingroom.jpg http://localhost:18792/api/reachy/vision/scene` → JSON with coherent caption.
- Sanity check model solo: `ollama run qwen2.5-vl:7b "describe this" < img.jpg`.

**Phase 5**
- After 30 s, inspect `c:\code\vault\ObsidianZero\00_Meta\_agent\vision\2026-04-23\` for new `.md`.
- Hold up sticky note "buy milk" — task appears in approval queue within one tick.
- Voice Reachy: "what do you see?" — reply matches frame content.

**Phase 6**
- Claude Desktop: `mcp__zero-api__describe_scene()` returns a sentence.
- Weekly digest contains "What you saw this week" section.

**Phase 7**
- Wear glasses, look at laptop — Reachy plays polite-idle. Look at Reachy — it perks up.

---

## Risks & dependencies

- **Meta DAT is preview.** No SLA, breaking changes expected. Isolated behind `SightProvider` so a pivot to Frame or MentraOS is one new file.
- **Windows camera locking.** DirectShow / WASAPI frequently refuses simultaneous access. Fully uninstall the old Tauri app before Phase 1; surface `locked_by` in `/camera/status`.
- **Daemon ↔ host_agent contention.** Confirm the headless daemon doesn't speculatively open the USB camera at startup, or host_agent's acquisition will fail.
- **VLM latency.** Qwen2.5-VL 7B is ~0.8 s on a 3090 and >10 s on CPU. `ambient_vision_tick` needs the `asyncio.Lock` backpressure explicitly called out in Phase 5.
- **Privacy / consent.** Always-on wearable camera is legally fraught in shared spaces. Global kill switch + visible indicator must ship before you wear this around other people.
- **Bandwidth / battery.** 1 fps JPEG ≈ 50 KB/frame — fine over LTE hotspot. Audio is the bigger budget; downshift to gesture-triggered capture when phone battery <30 %.

---

## Suggested execution order

1. **Phase 1** — fixes a visible bug, unblocks 3 UI panels, no external deps. Ship first.
2. **Phase 2** — small surface, huge leverage. Enables every subsequent phase.
3. **Phase 4** — makes Phase-1 webcam data actually useful against the *Reachy* camera; demo doesn't need glasses.
4. **Phase 5** — closes the loop. Zero visibly behaves differently with vision.
5. **Phase 6** — low effort, high daily utility through Claude Desktop + weekly digest.
6. **Phase 3** — in parallel with 5/6 on a separate Android Studio track. Riskiest.
7. **Phase 7** — only meaningful once 1 + 3 are both live.

Value accrues after Phase 2 even if Phase 3 slips indefinitely — a Logitech clip-on webcam is a valid `SightProvider` while the Meta bridge matures.

---

## Critical files

- [backend/app/services/reachy_service.py](backend/app/services/reachy_service.py)
- [backend/app/routers/reachy.py](backend/app/routers/reachy.py)
- [backend/app/services/reachy_vision_service.py](backend/app/services/reachy_vision_service.py)
- [backend/app/services/voice_loop_service.py](backend/app/services/voice_loop_service.py)
- [backend/app/services/reachy_context_service.py](backend/app/services/reachy_context_service.py)
- [backend/app/services/scheduler_service.py](backend/app/services/scheduler_service.py)
- [backend/app/infrastructure/unified_llm_client.py](backend/app/infrastructure/unified_llm_client.py)
- [backend/app/infrastructure/llm_router.py](backend/app/infrastructure/llm_router.py)
- [mcp_servers/zero_api_mcp.py](mcp_servers/zero_api_mcp.py)
- [frontend/src/pages/ReachyTeleopPage.tsx](frontend/src/pages/ReachyTeleopPage.tsx)
- [frontend/src/pages/ReachyMeetingsPage.tsx](frontend/src/pages/ReachyMeetingsPage.tsx)
- New: `backend/app/services/sight/{base,reachy_provider,webcam_provider,meta_rayban_provider,registry}.py`
- New: `backend/app/routers/sight.py`
- New: `backend/app/services/vision_vlm_service.py`
- New: `frontend/src/components/reachy/ReachyCameraViewer.tsx`
- New: `host_agent/routes/camera.py` (Windows host)
- New: `mobile/zero-wearable-bridge-android/` (Kotlin project)
