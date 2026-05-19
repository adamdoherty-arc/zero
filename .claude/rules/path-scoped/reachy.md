---
paths: ["**/reachy/**", "**/voice/**", "**/realtime/**"]
---

# Reachy + voice + realtime patterns

These rules apply when editing Reachy daemon, voice surface, or realtime files.

## Reachy phases 1-8 (recently shipped)

Voice UX shipped across 8 phases: realtime path, robot interaction, character content, daemon lifecycle, UI surfaces, memory facade integration, supervisor dispatch, email approval pool. The architecture is stable — don't unwind the patterns without a Sprint.

## Voice UX (do not undo)

- **Interactive Mode = primary voice surface.** `InteractiveModeBar` in the TopBar is the one-click toggle. Local realtime by default; OpenAI Realtime / Gemini Live as **explicit-only** fallbacks. Space toggles, Esc ends. 5-min idle auto-off for cost safety.
- **Local-first realtime.** The realtime path uses `reachy_realtime/local_handler.py` (streaming Whisper → vLLM qwen3-chat → Piper/edge-tts) by default. Cloud realtime backends are surfaced through the LLM badge popover but **never auto-selected** even if API keys are configured. Preferred-backend resolution lives in `backend/app/routers/reachy_realtime.py` `_enriched_config`.
- **FloatingVoiceButton is classic push-to-talk only.** Do NOT re-add realtime auto-promote. Two WebSocket instances = double billing.
- **LLMStatusBadge** in the TopBar is how the user picks/sees the active brain. Probe via `GET /api/reachy-intent/providers/status` (1-token probes, 15s cache, 5s per-provider timeout).
- **Kimi K2.5/K2.6 require `temperature=1` EXACTLY.** `kimi_provider.py` clamps this for any `kimi-k2*` model.

## Daemon / host_agent lifecycle (no watchdog)

Robot is OFF by default. The 2026-04-24 and 2026-05-11 outages were caused by silent watchdog failures — the new model trades automatic recovery for explicit user control.

- **Start robot:** open `/reachy` → DaemonPanel → **Start daemon**. Reachy daemon comes up on `:8000`.
- **Stop robot:** DaemonPanel → **Stop daemon**. Docker stack (assistant) keeps running.
- **Full robot tear-down:** close the host_agent console window.

**Do NOT** re-add the daemon watchdog (`POST /daemon/watchdog`), re-introduce scheduled tasks for the daemon, or auto-promote realtime backends.

## Realtime engine flag

`REACHY_REALTIME_ENGINE` selects `legacy` (default) or `pipecat`. `pipecat` is a no-op safety alias until the Pipecat bridge lands.

## Whisper default

`distil-large-v3` (~600MB faster-whisper). Override via `REACHY_LOCAL_WHISPER_MODEL`.

## Realtime tools (voice → agents)

Realtime tools exposed in `backend/app/services/reachy_realtime/tools.py`:
- `delegate_research`
- `draft_email`
- `bookkeeping_query`
- `supervisor_dispatch`

Reachy can spawn agents from voice via these. New voice-driven actions should be added here as tools, not as one-off router endpoints.

## Memory facade

`backend/app/services/memory_facade.py` is the single retrieval contract — fan-in across mem0 / episodic / user / blocks. `local_handler.py` calls it at session start to seed the system prompt. Enable mem0 backend with `ZERO_MEMORY_USE_MEM0=1`. **Use the facade — don't hit stores directly.**

## Key files

- `backend/app/services/reachy_realtime/local_handler.py` — local realtime path
- `backend/app/routers/reachy_realtime.py` — backend resolution / `_enriched_config`
- `backend/app/routers/reachy.py` — proxies daemon control to host_agent
- `host_agent/main.py` — FastAPI on `:18796` exposing `/daemon/{status,start,stop,restart,retry-scan,logs,issues,diagnostics,audio/reset,relink}`
- `host_agent/supervisor.py` — subprocess lifecycle + log tailing + atexit reaping (no watchdog code)
- `frontend/src/components/reachy/HostAgentOfflineBanner.tsx` — amber banner when host_agent is unreachable
- `frontend/src/components/reachy/StreamingHealthCard.tsx` — 4-card status grid (Robot / Daemon API / Video / Audio)
