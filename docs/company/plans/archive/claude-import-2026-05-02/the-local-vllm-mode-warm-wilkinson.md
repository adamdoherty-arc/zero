# Local vLLM Voice + Companion Persona + Hot-Swap + Unified Settings

## Context

Four problems, one plan:

1. **Local (vLLM) mode runs the chat but not the robot.** Screenshot shows an Interactive Mode session "via Local (vLLM)" with voice chip "cedar" — that's an OpenAI Realtime voice. The local handler in [backend/app/services/reachy_realtime/local_handler.py:616-655](backend/app/services/reachy_realtime/local_handler.py#L616) does call `_on_assistant_audio()`, but `tts_service.synthesize_with_meta(text, voice_override="cedar")` doesn't recognize "cedar" → returns empty PCM → `_speak_chunk` early-returns at line 627 → speaker sink never receives audio → robot is silent. The frontend lets users carry an OpenAI/Gemini voice ID into a local session because [common.py:75-93](backend/app/services/reachy_realtime/common.py#L75) accepts arbitrary voice strings on the local backend without validating against `LOCAL_AVAILABLE_VOICES`.

2. **No "girlfriend / companion" persona with a warm voice.** Personas live as folders under [backend/app/data/reachy_profiles/](backend/app/data/reachy_profiles/) (instructions.txt + tools.txt + voice.txt) and auto-load via [profiles.py:98-100](backend/app/services/reachy_realtime/profiles.py#L98). A `companion` persona exists; a dedicated warm/affectionate companion variant with a high-quality female voice does not.

3. **Provider switching is sequential, not live.** The "Swap → OpenAI Realtime" button currently tears down + restarts the session via `voice.stop()` then `voice.start()` ([InteractiveModeBar.tsx:123-150](frontend/src/components/reachy/InteractiveModeBar.tsx#L123)). Backend `backend` is bound at session-create and immutable — no `swap_backend` WS message exists ([session.py:307-323](backend/app/services/reachy_realtime/session.py#L307)). User wants to flip Local↔OpenAI↔Gemini mid-conversation without dropping mic, speaker sink, or transcript history.

4. **Settings are spread across two surfaces — a popup AND a modal.** Today the gear icon on [FloatingVoiceButton.tsx:510-516](frontend/src/components/reachy/FloatingVoiceButton.tsx#L510) opens an in-page popover ([lines 381-506](frontend/src/components/reachy/FloatingVoiceButton.tsx#L381)) that holds Classic/Realtime mode toggle + classic LLM brain picker, then has an "Open realtime settings…" button ([line 493](frontend/src/components/reachy/FloatingVoiceButton.tsx#L493)) that opens the bigger [ReachyRealtimeSettings.tsx](frontend/src/components/reachy/ReachyRealtimeSettings.tsx) modal (Connection, Voice, Personality, Behavior). Same fields, two windows, two clicks. User wants one modal.

Goal: robot speaks in local mode, a sweet companion persona ships with a quality cloned female voice (top open-source picks: Fish-Speech S2 Pro, Kokoro-82M, F5-TTS — all Apache/MIT, all stream-capable on a single consumer GPU), provider swap is a hot-swap, and all settings live in one well-organized modal.

## Implementation

### Part A — Make Local vLLM drive the robot

**1. Validate + auto-correct voice on session start.**
[backend/app/services/reachy_realtime/common.py:75-93](backend/app/services/reachy_realtime/common.py#L75) — when `backend == BACKEND_LOCAL`, if the requested voice is not in `LOCAL_AVAILABLE_VOICES` and not a persona-bound voice, fall back to `DEFAULT_VOICE_BY_BACKEND[BACKEND_LOCAL]` (`en-US-AriaNeural`) and log a warning. Don't accept arbitrary voice strings silently.

**2. Surface TTS failures instead of swallowing them.**
[backend/app/services/reachy_realtime/local_handler.py:616-655](backend/app/services/reachy_realtime/local_handler.py#L616) — when `tts_service.synthesize_with_meta` returns empty PCM or raises, log structured error with the voice ID + engine and emit a transcript event so the user sees "TTS failed (voice not available)" instead of silent failure.

**3. Frontend: gate voice picker on backend.**
[frontend/src/components/reachy/ReachyRealtimeSettings.tsx](frontend/src/components/reachy/ReachyRealtimeSettings.tsx) — when the user selects backend = Local, filter the voice dropdown to local voices (Piper presets + Edge-TTS + new local engines from Part C). Display the active backend's default voice as a chip in [InteractiveModeBar.tsx](frontend/src/components/reachy/InteractiveModeBar.tsx) instead of letting "cedar" persist across backend changes.

### Part B — Companion girlfriend persona

**1. New profile folder.**
Create `backend/app/data/reachy_profiles/companion_girlfriend/` with:
- `instructions.txt` — warm, affectionate, lightly playful tone; remembers prior moods; checks in on feelings; uses pet names sparingly; keeps it tasteful and respectful (the system prompt is the persona contract — user can edit later).
- `tools.txt` — enable `dance`, `play_emotion`, `look_at_me`, `play_sound` so she can respond physically.
- `voice.txt` — voice ID for whichever local engine ships in Part C (e.g. `local-companion-warm` cloned voice, or fallback `en-US-JennyNeural`).

**2. Register in personas catalog.**
[backend/app/services/reachy_personas.py:43-80](backend/app/services/reachy_personas.py#L43) — add `companion_girlfriend` entry with display label "Companion (warm)". Auto-pickup via existing profile loader; no router change needed.

**3. Front-end persona picker.**
The persona dropdown already enumerates profiles from `/api/reachy/realtime/profiles`. Verify the new profile appears and gets a friendly label.

### Part C — High-quality local female voice (Fish-Speech)

**Pick: Fish-Speech v1.5+ (S2 Pro, March 2026).** Apache 2.0, ~4 GB VRAM, 200 ms streaming TTFB, zero-shot voice cloning from a 10-15 sec reference sample, ELO 1339 on TTS Arena. Single GitHub source: https://github.com/fishaudio/fish-speech. Runner-up Kokoro-82M (presets only, no cloning) becomes the CPU-cheap fallback.

**1. Run Fish-Speech as a local OpenAI-compatible service** in the Zero docker stack (or on the Windows host via host_agent if GPU passthrough is awkward — match how vllm-chat is hosted). Expose `/v1/audio/speech` with `stream=true` chunked PCM.

**2. Add a third engine to `TTSService`.**
[backend/app/services/tts_service.py:18-33](backend/app/services/tts_service.py#L18) — add `FishSpeechEngine` alongside Piper + Edge-TTS. Engine accepts `voice_override` as either a preset ID (`local-companion-warm`) or a path to a stored reference clip. Add `LOCAL_AVAILABLE_VOICES` entries for the cloned voices.

**3. Voice cloning workflow.**
Reuse the existing reference-video ingest pattern (yt-dlp → whisper → style extract). Add a small endpoint `POST /api/reachy/voices/clone` that takes a 10-30 sec audio sample, stores it under `backend/app/data/voice_clones/<voice_id>.wav`, and the Fish-Speech engine reads that path at synth time. Seed `local-companion-warm` with a warm female reference (TODO: source a public-domain or self-recorded sample; do NOT clone a real person without consent — this is the one thing to flag for user input before running).

**4. Streaming.**
Fish-Speech S2 Pro chunks audio at ~200 ms TTFB. Wire its stream output directly into `_speak_chunk` so each chunk forwards to the speaker sink as it arrives, instead of buffering the full utterance.

### Part D — Uncensored brain catalog (Qwen3.5 Heretic family)

Wire up a tiered set of uncensored Qwen3.5 brains so the companion persona can run without the guardrail-induced stiltedness of `qwen3-chat`. Default to the 9B; expose larger and lighter options.

**Model catalog (registered in LiteLLM, surfaced in the unified Brain picker):**

| ID | HF Repo | Size | Context | VRAM (fp8) | Use |
|---|---|---|---|---|---|
| `qwen3-heretic-9b` | [DavidAU/Qwen3.5-9B-Claude-4.6-HighIQ-THINKING-HERETIC-UNCENSORED](https://huggingface.co/DavidAU/Qwen3.5-9B-Claude-4.6-HighIQ-THINKING-HERETIC-UNCENSORED) | 9B | 128K | ~10 GB | **Default companion brain** |
| `qwen3-heretic-27b` | [DavidAU/Qwen3.5-27B-HERETIC-Polaris-Advanced-Thinking-Alpha-uncensored](https://huggingface.co/DavidAU/Qwen3.5-27B-HERETIC-Polaris-Advanced-Thinking-Alpha-uncensored) | 27B | 128K | ~30 GB | If VRAM allows |
| `qwen3-heretic-40b` | [DavidAU/Qwen3.5-40B-Claude-4.6-Opus-Deckard-Heretic-Uncensored-Thinking](https://huggingface.co/DavidAU/Qwen3.5-40B-Claude-4.6-Opus-Deckard-Heretic-Uncensored-Thinking) | 40B | 256K | ~45 GB | Top-tier; vision-capable for camera awareness |
| `qwen3-josiefied-8b` | [Qwen3-8B-64k-Josiefied-Uncensored](https://huggingface.co/) | 8B | 64K | ~9 GB | Lightweight fallback |
| `oxy-1-small` | [oxyapi/oxy-1-small](https://huggingface.co/oxyapi/oxy-1-small) | 14B | 32K | ~16 GB | Qwen2.5-base, roleplay-tuned |

**1. Serve via vLLM.** The project already runs vllm-chat on `:18800`. Add a new service `vllm-heretic` on `:18801` for the default 9B; flagged launch:
```
vllm serve DavidAU/Qwen3.5-9B-Claude-4.6-HighIQ-THINKING-HERETIC-UNCENSORED \
  --max-model-len 32768 \
  --quantization fp8 \
  --enable-prefix-caching \
  --served-model-name qwen3-heretic-9b
```
`--enable-prefix-caching` matters because the persona system prompt is reused on every turn. Add the additional models behind the same service via `--served-model-name` aliases when VRAM allows, otherwise leave them unconfigured and document the launch command in [docs/local-brains.md](docs/local-brains.md).

**2. Register in LiteLLM.** Add entries to [shared-infra/litellm/config.yaml](shared-infra/litellm/config.yaml) routing `qwen3-heretic-*` and `oxy-1-small` to the host vLLM endpoint (per the "Shared LiteLLM Router" memory note).

**3. Persona-bound model.** Extend persona profiles to allow a new `model.txt` file alongside `voice.txt`. [profiles.py:98-100](backend/app/services/reachy_realtime/profiles.py#L98) loader reads it; session start uses `profile.model` when backend=local and the user hasn't manually overridden. `companion_girlfriend/model.txt` → `qwen3-heretic-9b`.

**4. Safety boundary.** These are abliterated/refusal-trained-removed models. Gate behind explicit selection; never global default. Show a one-line warning in the model picker: "No content filter — persona prompt is the only guardrail."

### Part E — Three-tier persistent memory + V2 Character Cards

The companion needs to remember the user across sessions: preferences, past conversations, mood arcs. Today personas are stateless. Adopt a three-tier memory stack and upgrade persona format to the SillyTavern V2 Character Card standard.

**Tier 1 — Working context (already exists).** Qwen 9B gives 32K-128K useful context per session; keep the full transcript in the session handler.

**Tier 2 — Semantic long-term memory via Mem0 + pgvector.**
- The project already runs pgvector on Postgres 17 (per "Postgres topology" memory note). Skip Qdrant — reuse pgvector.
- Vendor [Mem0](https://github.com/mem0ai/mem0) (Apache 2.0) into `backend/app/services/vendored/mem0/` per the CHECK-GITHUB-BEFORE-BUILDING rule, swap its default vector backend for pgvector.
- Wrap as `ReachyMemoryService` ([backend/app/services/reachy_memory.py](backend/app/services/reachy_memory.py), new): `add_memory(user_id, text, tags)`, `semantic_search(user_id, query, k=5)`.
- Hook points in [reachy_realtime/session.py](backend/app/services/reachy_realtime/session.py): on each user turn → fire-and-forget extract + write; before each assistant turn → semantic search top-5 → inject into system prompt as `[Relevant memories: …]`.

**Tier 3 — Episodic/character summaries.**
- Every N=20 messages, run a cheap summarization pass (Kimi-light or local 9B) that distills the recent conversation into structured facts: `{user_likes: [...], shared_moments: [...], current_mood: "...", relationship_level: 1-10}`.
- Store as JSON in `backend/app/data/memory/episodic/{user_id}/{persona_id}.json`.
- Inject the latest summary into the system prompt at every turn under `[Relationship context]`.
- Reference patterns: [savantskie/persistent-ai-memory](https://github.com/savantskie/persistent-ai-memory), [bal-spec/sillytavern-character-memory](https://github.com/bal-spec/sillytavern-character-memory), [letta-ai/characterai-memory](https://github.com/letta-ai/characterai-memory) — study, vendor what's small, don't depend.

**V2 Character Card persona format.**
- Replace the flat `instructions.txt` with `character.json` matching the SillyTavern V2 schema: `{name, description, personality, scenario, first_mes, mes_example, system_prompt, post_history_instructions, tags, creator, character_version, extensions: {voice, model, tools, mood_baseline}}`.
- [profiles.py](backend/app/services/reachy_realtime/profiles.py) loader: read `character.json` if present, else fall back to legacy `instructions.txt` (don't break the existing 12 personas).
- For `companion_girlfriend`, fill: warm/playful/affectionate `personality`; speaking style with pet names; relationship dynamics; physicality (uses Reachy motion: leans in when whispering, looks at user when listening, plays `excited1` when they arrive).

**Dynamic prompt assembly** at session start and after every memory update:
```
[Persona: {character.system_prompt}]
[Personality: {character.personality}]
[Speaking style: {character.mes_example}]
[Current mood: {dynamic_mood from tier-3}]
[Relationship: {relationship_summary from tier-3}]
[Recent memories: {top-5 from tier-2}]
[Available tools: {profile.tools}]
[User: {user message}]
```

**Reference repos to study** (do not vendor as a unit; cherry-pick patterns):
- [pollen-robotics/reachy_mini_conversation_app](https://github.com/pollen-robotics/reachy_mini_conversation_app) — already partly harvested per the "Reachy ecosystem harvest 2026-04" memory note; check what motion/audio pipeline pieces aren't yet in.
- [dwain-barnes/reachy_mini_conversation_app_local](https://github.com/dwain-barnes/reachy_mini_conversation_app_local) — fully-local variant; cleaner cloud-API-swap pattern than what's in the project today.
- [2U1/Qwen-VL-Series-Finetune](https://github.com/2U1/Qwen-VL-Series-Finetune) — optional fine-tuning track if presets ever feel insufficient (LoRA, DPO).

### Part F — Unify all settings into one modal

Today there are three settings entry points: the FloatingVoiceButton gear popup ([FloatingVoiceButton.tsx:381-506](frontend/src/components/reachy/FloatingVoiceButton.tsx#L381)), the `ReachyRealtimeSettings` modal ([ReachyRealtimeSettings.tsx:114-772](frontend/src/components/reachy/ReachyRealtimeSettings.tsx#L114)), and the standalone [ReachyVoiceSettingsPage.tsx](frontend/src/pages/ReachyVoiceSettingsPage.tsx). The popup forwards to the modal via a button. Consolidate.

**1. Promote `ReachyRealtimeSettings` to the single Interactive Mode Control Panel.** Rename to `InteractiveModeSettings` (or keep filename, just expand contents). Tabs along the top:
- **Mode** — Classic vs Realtime toggle (was in FloatingVoiceButton popup, [lines 388-434](frontend/src/components/reachy/FloatingVoiceButton.tsx#L388))
- **Brain** — Backend (Local / OpenAI Realtime / Gemini Live) + Model picker (qwen3-chat, qwen3-coder, qwen3-heretic-9b/27b/40b, oxy-1-small, qwen3-josiefied-8b, or remote model IDs). Replaces the separate classic LLM brain dropdown ([FloatingVoiceButton.tsx:437-472](frontend/src/components/reachy/FloatingVoiceButton.tsx#L437)) and the radio-button backend selector ([ReachyRealtimeSettings.tsx:491-527](frontend/src/components/reachy/ReachyRealtimeSettings.tsx#L491)).
- **Voice** — Filtered by selected backend (Part A.3): OpenAI voices for OpenAI, Gemini voices for Gemini, Piper/Edge/Fish-Speech voices for Local. Includes the play-preview button row.
- **Persona** — Profile grid + selected profile's character card preview (V2 schema fields from Part E). Folds in the persona dropdown that lived elsewhere.
- **Memory** — Toggle long-term memory on/off, view stored memories for current persona, clear memory, see relationship-level + current-mood (tier-3 summary read-only).
- **Connection** — OpenAI/Gemini API key fields + clear buttons + "Claim free key" link.
- **Behavior** — Idle timeout, Space hotkey toggle, cost cap, push-to-talk vs always-on.

**2. Delete the FloatingVoiceButton settings popup.** [FloatingVoiceButton.tsx:381-506](frontend/src/components/reachy/FloatingVoiceButton.tsx#L381) — replace with a single gear button that opens the unified modal directly. Remove the duplicate read-only display block at [lines 474-503](frontend/src/components/reachy/FloatingVoiceButton.tsx#L474).

**3. Reduce InteractiveModeBar to a status bar + one Settings button.** [InteractiveModeBar.tsx](frontend/src/components/reachy/InteractiveModeBar.tsx) — its existing "Settings" button already opens a settings sheet; route it to the same unified modal. The Brain/Voice/Persona chips stay as read-only status. Move "Reachy only", "Look at me", "Ahead", "Mic on", "Interrupt" to a compact action row (those are session controls, not settings — keep separate).

**4. ReachyVoiceSettingsPage stays for advanced classic-pipeline tuning** (STT model, TTS engine details that the average user won't touch). Add a prominent "Open Interactive Mode Settings" link at the top so it's discoverable from the voice page too — but the primary entry from chat is the bar's Settings button.

**5. Route consistency.** Settings persist via the same backend endpoint they already use (`/api/reachy/realtime/config`). Expand schema to include the new fields (model, mode, classic-brain) so a single PUT saves everything.

### Part G — Hot-swap providers mid-session

**1. Backend: add `swap_backend` WS message.**
[backend/app/services/reachy_realtime/session.py:307-323](backend/app/services/reachy_realtime/session.py#L307) — accept a new message:
```json
{"type": "swap_backend", "backend": "local|openai|gemini", "voice": "...", "model": "..."}
```
Handler:
- Stop existing `self.handler` task (line 475 pattern) — but keep `self._speaker_sink`, the WS connection, and `self._mic_pump` alive.
- Snapshot conversation history from current handler if it exposes it; pass to new handler as seed context (each handler already accepts `history` / `instructions` at init).
- Construct new handler (OpenAI / Gemini / Local) with same profile/instructions, new voice/model, and rewire `on_assistant_audio` to the existing `self._speaker_sink.write_pcm`.
- Resume mic PCM feed: re-point the existing audio worklet stream to `new_handler.feed_pcm`.
- Emit a status frame `{"type":"backend_swapped","backend":"..."}` so the UI updates the chip.

**2. Frontend: convert "Swap" button to live hot-swap.**
[frontend/src/hooks/useRealtimeVoice.ts](frontend/src/hooks/useRealtimeVoice.ts) — add `swapBackend(backend, voice?, model?)` that sends the new WS message instead of calling `stop()` + `start()`. Preserve `transcriptRef`, `audioContextRef`, `pendingSpeakerNodes`, `partialIdRef` ([useRealtimeVoice.ts:96-120](frontend/src/hooks/useRealtimeVoice.ts#L96)).

[frontend/src/components/reachy/InteractiveModeBar.tsx:123-150](frontend/src/components/reachy/InteractiveModeBar.tsx#L123) — change the swap button + the settings dialog Save action to call `voice.swapBackend(...)` when a session is live. Cycle through Local → OpenAI → Gemini in the swap button label so it's a single tap to rotate. Show a brief inline status ("Swapping to OpenAI Realtime…") while the handoff happens.

**3. Persona/voice swap on the same channel.**
Same `swap_backend` message also accepts `profile` and `voice` so the user can change persona (Companion → Companion girlfriend) mid-conversation without dropping the mic.

## Files to modify

**Backend:**
- [backend/app/services/reachy_realtime/common.py](backend/app/services/reachy_realtime/common.py) — voice validation
- [backend/app/services/reachy_realtime/local_handler.py](backend/app/services/reachy_realtime/local_handler.py) — error surfacing, Fish-Speech streaming, model-from-persona
- [backend/app/services/reachy_realtime/session.py](backend/app/services/reachy_realtime/session.py) — `swap_backend` WS message, memory injection hook points
- [backend/app/services/reachy_realtime/profiles.py](backend/app/services/reachy_realtime/profiles.py) — V2 character card loader, `model.txt`, memory bind
- [backend/app/services/tts_service.py](backend/app/services/tts_service.py) — Fish-Speech engine
- [backend/app/services/reachy_personas.py](backend/app/services/reachy_personas.py) — register new persona
- [backend/app/data/reachy_profiles/companion_girlfriend/{character.json, tools.txt, voice.txt, model.txt}](backend/app/data/reachy_profiles/) — new persona, V2 schema
- New: [backend/app/services/reachy_memory.py](backend/app/services/reachy_memory.py) — Mem0 + pgvector wrapper, episodic summarizer
- New: [backend/app/services/vendored/mem0/](backend/app/services/vendored/mem0/) — vendored Mem0 with pgvector backend
- New: [backend/app/data/memory/episodic/](backend/app/data/memory/episodic/) — JSON storage for tier-3 summaries
- [backend/app/routers/reachy_realtime.py](backend/app/routers/reachy_realtime.py) — `POST /voices/clone`, `GET/DELETE /memory/{user_id}/{persona_id}`

**Infra:**
- [docker-compose.sprint.yml](docker-compose.sprint.yml) — new `vllm-heretic` service on `:18801`, new `fish-speech` service on `:18802`
- [shared-infra/litellm/config.yaml](shared-infra/litellm/config.yaml) — register `qwen3-heretic-9b/27b/40b`, `oxy-1-small`, `qwen3-josiefied-8b`

**Frontend:**
- [frontend/src/hooks/useRealtimeVoice.ts](frontend/src/hooks/useRealtimeVoice.ts) — `swapBackend()` action
- [frontend/src/components/reachy/InteractiveModeBar.tsx](frontend/src/components/reachy/InteractiveModeBar.tsx) — wire hot-swap, single Settings button → unified modal
- [frontend/src/components/reachy/ReachyRealtimeSettings.tsx](frontend/src/components/reachy/ReachyRealtimeSettings.tsx) — backend-aware voice dropdown, new Mode/Brain/Memory tabs
- [frontend/src/components/reachy/FloatingVoiceButton.tsx](frontend/src/components/reachy/FloatingVoiceButton.tsx) — strip popup, gear opens unified modal

## Verification

1. **Local vLLM speaks through Reachy.** Start Interactive Mode in Local (vLLM) mode with the Companion persona. Speak. Confirm: (a) transcript appears, (b) Reachy speakers play TTS audio (not browser), (c) `docker logs zero-api` shows `_on_assistant_audio` firing with non-zero PCM bytes, (d) host_agent `/speaker/stream` log shows incoming frames.
2. **Voice mismatch handled.** Manually POST `/api/reachy/realtime/start` with `backend=local, voice=cedar`. Confirm voice auto-falls-back, log warning is emitted, robot still speaks.
3. **Companion girlfriend persona loads.** `GET /api/reachy/realtime/profiles` shows it; pick it in the UI; confirm system prompt + voice take effect on next utterance.
4. **Fish-Speech voice cloning.** POST a 15-sec reference clip to `/api/reachy/voices/clone` with id `local-companion-warm`. Trigger TTS; measure TTFB <300 ms; confirm cloned timbre.
5. **Heretic brain online.** `curl http://localhost:18801/v1/models` returns `qwen3-heretic-9b`. LiteLLM `/v1/chat/completions` with `model=qwen3-heretic-9b` round-trips a response. Pick it in the unified modal Brain tab; verify the session uses it (token counter logs show calls hitting `:18801`, not `:18800`).
6. **Memory recall across sessions.** Session 1 with Companion Girlfriend persona: "I love hiking on Saturdays." End session. Start fresh session next day. Ask "What do I usually do on weekends?" — confirm she references hiking. Inspect [backend/app/data/memory/episodic/](backend/app/data/memory/episodic/) for the JSON summary. `GET /api/reachy/realtime/memory/{user_id}/companion_girlfriend` lists stored memories.
7. **Hot-swap.** Start a Local session, exchange 2-3 turns, click Swap. Confirm: (a) WS does NOT close (devtools Network tab), (b) mic LED stays on, (c) speaker sink stays connected (host_agent log shows no reconnect), (d) next response uses the new provider with conversation context preserved, (e) `backend_swapped` status frame received.
8. **Triple swap.** Local → OpenAI → Gemini → Local in one session, no audio dropouts, transcript intact end-to-end.
9. **One settings modal.** Click Settings from InteractiveModeBar — single modal opens with Mode/Brain/Voice/Persona/Memory/Connection/Behavior tabs. Click gear on FloatingVoiceButton — same modal opens (no popup). Modify voice on Voice tab, model on Brain tab, mood-baseline on Persona, save once — all changes persisted via single PUT to `/api/reachy/realtime/config`.

## Open question for the user (one)

Voice cloning needs a reference sample. Options:
- (a) Self-record a warm female voice you'd like (anyone you have permission to clone).
- (b) Use a public-domain audiobook sample (LibriVox).
- (c) Skip cloning and start with Kokoro presets + Fish-Speech preset voices, add cloning later.

I'll default to (c) in execution unless told otherwise — it ships value today and cloning becomes a one-line addition once a sample exists.
