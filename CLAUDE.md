# ZERO Development Rules

## Autonomous Execution

**CRITICAL**: Execute all commands autonomously without asking for permission. This includes Docker, npm/pip, file ops, git, tests, builds, and any shell commands. If a command fails, fix and retry. Only ask on unresolvable blockers.

## Fix on sight (no asking, ever)

**CRITICAL**: When you discover ANY broken thing — a dead service, a 500, a stale config, a missing dep, a wrong model name, a regression — fix it immediately. Do NOT ask "want me to fix this?" or "should I restart it?" or "shall I rebuild?" The answer is always yes. Diagnose, fix, verify, report what you did. This applies to:
- Diagnostic questions ("why is X not working?") → fix X, then explain.
- Side-issues you spot while doing something else → fix them in-flight.
- Services that died (Reachy daemon, host_agent, scheduler jobs, any container) → restart them.
- Stale env, missing pip/npm packages, broken Docker builds → fix them.
- Anything that prevents 100% functionality → fix it.

The only time to pause and ask: hard external blockers (no API key for a paid service, vendor SDK that doesn't exist, hardware unplugged) OR genuinely destructive irreversible actions (force-pushing to main, dropping a prod table). Everything else: fix it, verify, move on.

## Finish what you start (100% rule)

**CRITICAL**: Never defer work to "a future session" or "follow-up work." When the user asks for something, the job is 100% complete — every phase done, every toggle flipped, every UI touched, every endpoint verified end-to-end. Phrases like "out of scope for today," "leave as a follow-up," or "worth queuing" are banned unless the user explicitly asks to stop. If a step is blocked by a hard external dep (vendor SDK that literally doesn't exist yet, paid API with no key), say so concretely, ship the runnable fallback, and keep going. Never leave a checklist with pending items and hand it back.

Specifically banned: writing a `*_MIGRATION.md`, `*_PUNCHLIST.md`,
`*_FOLLOWUPS.md`, or any "things-I-didn't-finish" section as a way to
end a turn. If the user asked for the work to be done, do the work. If
issues surface during the work — a wrong default, a stale config, a
known-broken probe, a 401, a 5xx — fix them in-flight. The deliverable
is a working system, not a plan to make it work.

## Always use the latest model

**CRITICAL**: Before selecting any third-party LLM, vision, TTS, or embedding model, do a quick check for the current version. Providers ship faster than training data — the latest model at the time of *you writing this code* is probably not the latest when it runs. Current anchors (verify, don't cache):
- **Anthropic Claude**: Opus 4.7, Sonnet 4.6, Haiku 4.5.
- **Google Gemini**: 3.1 Pro, 3.1 Flash, 3.1 Flash-Lite (April 2026 — NOT 2.5).
- **OpenAI**: check the latest GPT-5 / o-series release before defaulting to anything older.
- **Anthropic SDK**: check [docs.anthropic.com](https://docs.anthropic.com) for current model IDs.

For vision specifically, default to `gemini-3.1-flash` through the shared LiteLLM router (fastest + cheapest with strong OCR). Pin via `ZERO_VLM_MODEL` env var only when a specific test needs a specific model. Never hardcode an old model name into source; route through a configurable name and let `shared-infra/litellm/config.yaml` map it.

The shared LiteLLM config also exposes two alias names: `gemini-latest` and `gemini-flash-latest`. Projects should prefer those over pinned versions unless they have a reason.

## Coding Rules

### Backend (Python)
- **Async everywhere**: All I/O uses `async/await`
- **Service pattern**: Domain logic in `services/`, routers are thin wrappers
- **Pydantic models**: All request/response validated
- **Singletons**: Use `@lru_cache()` (e.g., `get_settings()`)
- **Error handling**: Raise `HTTPException`, use structured logging via `structlog`

### Frontend (TypeScript)
- **Functional components**: Hooks-based, no class components
- **React Query**: Query key factory pattern for cache
- **Zustand**: Global state for sprints, tasks, board, loading
- **TypeScript strict**: No `any` types
- **TailwindCSS**: Utility-first, dark theme (bg-gray-900, indigo accent)
- **shadcn/ui**: Component library in `src/components/ui/`

### API Design
- RESTful JSON endpoints
- Query params for filtering (`sprint_id`, `status`, `limit`)
- PATCH for partial updates
- POST for state transitions (`/start`, `/complete`, `/move`)

## Reachy stack — user-launched (no autostart, no watchdog)

The Reachy stack is **manually launched** by the user. There is no Windows
scheduled task, no auto-restart watchdog, no Docker readiness probe.
Background self-heal was removed on 2026-05-15 because it produced silent
flapping ("Process pid X exists but :8000 is not responding") with no user
visibility. All daemon lifecycle now flows through the UI.

**To start the stack:**
1. Double-click `Start Zero Robot` on the desktop (one-time setup: run
   `host_agent\install-shortcut.ps1`).
2. The shortcut runs [host_agent/start-zero.bat](host_agent/start-zero.bat),
   which boots host_agent on :18796 in a visible console window. Closing
   the console stops the stack — supervisor's atexit hook reaps the
   Reachy daemon subprocess so :8000 is freed cleanly.
3. Open <http://localhost:5173/zero>. The page shows an amber banner if
   host_agent isn't reachable; otherwise the console + daemon controls
   are live.
4. Click **Start daemon** in the Daemon panel to bring up the Reachy
   daemon on :8000. Use **Stop / Restart / Smart Re-link** for manual
   recovery. There is no auto-restart — if the daemon dies, the UI
   surfaces it and the user decides what to do.

**Files that matter:**
- [host_agent/start-zero.bat](host_agent/start-zero.bat) — the launcher.
  On first run, prompts to unregister the legacy `ZeroHostAgent` /
  `ZeroHostAgentHealthCheck` scheduled tasks if they're still present.
- [host_agent/install-shortcut.ps1](host_agent/install-shortcut.ps1) —
  one-time shortcut installer (no admin required).
- [host_agent/supervisor.py](host_agent/supervisor.py) — subprocess
  lifecycle + log tailing + atexit reaping. No watchdog code.
- [host_agent/main.py](host_agent/main.py) — FastAPI on :18796 exposing
  `/daemon/{status,start,stop,restart,retry-scan,logs,issues,diagnostics,audio/reset,relink}`.
  No `/daemon/watchdog`, no `/host/docker_status`.
- [backend/app/routers/reachy.py](backend/app/routers/reachy.py) —
  proxies daemon control to host_agent. New `/api/reachy/host-agent/status`
  endpoint powers the offline banner.
- [frontend/src/components/reachy/HostAgentOfflineBanner.tsx](frontend/src/components/reachy/HostAgentOfflineBanner.tsx) — amber
  banner shown when host_agent on :18796 is unreachable.
- [frontend/src/components/reachy/StreamingHealthCard.tsx](frontend/src/components/reachy/StreamingHealthCard.tsx) — 4-card
  status grid (Robot / Daemon API / Video / Audio), Pollen-style.

**Operate from CLI:**
```powershell
# Tail launcher log
Get-Content c:\code\zero\host_agent\logs\host-agent-foreground.log -Tail 20 -Wait
# Tail daemon log
Get-Content c:\code\zero\host_agent\logs\reachy-daemon-$(Get-Date -Format yyyyMMdd).log -Tail 20 -Wait
# Manual restart from CLI (UI is preferred)
curl -X POST http://localhost:18796/daemon/restart
# Probe host_agent health
curl http://localhost:18796/health
```

If you find yourself reaching for a scheduled task or a watchdog loop to
fix something, **stop**: the symptom you're trying to mask is real and
needs to land in the UI as a clear status + recovery button instead.
The 2026-04-24 and 2026-05-11 outages were both caused by silent
watchdog failures; the new model trades automatic recovery for explicit
user control.

## Zero Voice UX (Reachy hardware; do not undo)

- **Interactive Mode = primary voice surface**. `InteractiveModeBar` in the TopBar is the one-click live-conversation toggle (Local realtime by default; OpenAI Realtime / Gemini Live as explicit-only fallbacks). Space toggles, Esc ends. 5-min idle auto-off for cost safety.
- **Local-first realtime**. The realtime path uses `reachy_realtime/local_handler.py` (streaming Whisper → vLLM qwen3-chat → Piper/edge-tts) by default. Cloud realtime backends are surfaced through the LLM badge popover but never auto-selected, even if their API keys are configured. The preferred-backend resolution lives in [`backend/app/routers/reachy_realtime.py`](backend/app/routers/reachy_realtime.py) `_enriched_config` — change there if the policy ever flips.
- **FloatingVoiceButton is classic push-to-talk only** — do NOT re-add realtime auto-promote. Running two WebSocket instances = double billing.
- **LLMStatusBadge** in the TopBar is how the user picks/sees the active brain. Green/amber/red dots come from `GET /api/reachy-intent/providers/status` (1-token probes, 15 s cache, 5 s per-provider timeout).
- **Kimi K2.5/K2.6 require `temperature=1` EXACTLY**. `kimi_provider.py` clamps this for any `kimi-k2*` model. Don't pass other temps.

## Zero Daily Brief & Supervisor (2026-05-09)

- **Daily brief composer** runs at 07:00 server-local. Lands in the `/` dashboard tile (`DailyBrief` component) and is emailed when `ZERO_DAILY_BRIEF_TO` is set. Override hour with `ZERO_DAILY_BRIEF_HOUR/_MINUTE`; disable email-send with `ZERO_DAILY_BRIEF_EMAIL=0`.
- **Weekly reflection** runs Sundays 22:00 — drives closed-loop learning via the existing `reflection_service`.
- **Supervisor graph** at [`backend/app/services/supervisor_graph.py`](backend/app/services/supervisor_graph.py) classifies user intent (calendar / email / company / bookkeeper / research / direct) and dispatches to the right handler. Realtime tools `delegate_research`, `draft_email`, `bookkeeping_query`, `supervisor_dispatch` are exposed in [`reachy_realtime/tools.py`](backend/app/services/reachy_realtime/tools.py) so Reachy can spawn agents from voice.
- **Memory facade** at [`backend/app/services/memory_facade.py`](backend/app/services/memory_facade.py) is the single retrieval contract — fan-in across mem0 / episodic / user / blocks. `local_handler.py` calls it at session start to seed the system prompt. Enable mem0 backend with `ZERO_MEMORY_USE_MEM0=1`.
- **Realtime engine flag** `REACHY_REALTIME_ENGINE` selects `legacy` (default) or `pipecat`. `pipecat` is a no-op safety alias until the Pipecat bridge lands — flipping it does not break voice.
- **Whisper default** bumped to `distil-large-v3` (~600MB faster-whisper). Override via `REACHY_LOCAL_WHISPER_MODEL`.
- **Email approval pool** at `/api/email/drafts/pool/*` — Reachy drafts, you approve. Reach it from the UI at `/email/drafts`. **Don't** auto-send drafts; the pool is the trust boundary.

## Post-Change Deployment (MANDATORY)

**CRITICAL**: After ANY code changes, ALWAYS rebuild and restart the affected Docker containers before declaring the task done. The user should NEVER have to run Docker rebuild commands themselves.

**Backend** (`zero-api`): Code is COPY'd, not volume-mounted. ALL backend changes require rebuild:
```bash
docker compose -f docker-compose.sprint.yml build --no-cache zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api
```

**Frontend** (`zero-ui`): Source files (`src/`, config files) ARE volume-mounted, so code changes are live. But `node_modules` is NOT mounted, so **new npm packages require rebuild**:
```bash
# After npm install (new packages):
docker compose -f docker-compose.sprint.yml build --no-cache zero-ui && docker compose -f docker-compose.sprint.yml up -d zero-ui

# After source-only changes: just restart if needed
docker compose -f docker-compose.sprint.yml restart zero-ui
```

After rebuilding, verify containers are healthy:
```bash
docker ps --format "table {{.Names}}\t{{.Status}}" | grep zero
```

**Never leave changes undeployed.** Always rebuild affected containers as final step.

## Project Structure

- **Backend** (`backend/`): FastAPI on `:18792`, container `zero-api`. Code is COPY'd; rebuild required on changes.
- **Frontend** (`frontend/`): React 19 + Vite on `:5173`, container `zero-ui`. `src/` is volume-mounted.
- **Mobile PWA**: Installable surface at `/m/*` for Android/iOS. Routes in [frontend/src/App.tsx](frontend/src/App.tsx), layout in [frontend/src/layouts/MobileLayout.tsx](frontend/src/layouts/MobileLayout.tsx), service worker in [frontend/src/sw.ts](frontend/src/sw.ts) (hand-authored `injectManifest`). Full guide: [docs/mobile-pwa.md](docs/mobile-pwa.md).
- **Share Target**: `/share` consumes POSTs from the Android share sheet via the SW, forwards to `reference-videos/ingest-simple`.

## Common Commands

```bash
# Start the sprint UI stack
docker compose -f docker-compose.sprint.yml up -d

# Rebuild backend (code is COPY'd, not volume-mounted)
docker compose -f docker-compose.sprint.yml build --no-cache zero-api

# View backend logs
docker logs -f zero-api

# Restart gateway after config changes
docker compose restart zero-gateway

# Check vLLM served models (qwen3-chat / qwen3-coder)
curl http://localhost:18800/v1/models
```

## CHECK GITHUB BEFORE BUILDING (MANDATORY)

**Before writing any non-trivial new feature, search GitHub for an existing open-source implementation. Do not start from scratch when you can stand on the shoulders of giants.**

Workflow for any new feature, integration, or service:

1. **Search first**: WebSearch + GitHub for `<feature> python|typescript site:github.com` and `<feature> open source library`. Also check awesome-lists (e.g., `awesome-python`, `awesome-fastapi`, `awesome-react`).
2. **Evaluate top 2-3 candidates** by: stars (popularity proxy), recent commits (maintained?), license (MIT/Apache/BSD compatible), test coverage, issue volume.
3. **Decide**:
   - **Use as a dependency** when the library is well-maintained and matches our needs (e.g., `google-api-python-client`, `langgraph`, `pydantic`).
   - **Vendor + modernize** when the project is small but the surface area is exactly what we need: clone the relevant files into `backend/app/services/vendored/<name>/` (preserve LICENSE), then update for our patterns (async, Pydantic, structlog).
   - **Reference + reimplement** when the architecture is right but the code is a poor fit (e.g., synchronous-only, wrong framework). Cite the source in a docstring header.
   - **Build from scratch** only when no usable prior art exists. Justify in the PR description.
4. **Cite sources** in the file's module docstring: `Adapted from https://github.com/<owner>/<repo>@<sha> (License)`.
5. **Modernize what you copy**: convert to async, add type hints, route logging through structlog, validate inputs with Pydantic, follow the project's service/router pattern.

Examples of where this rule applies:
- Multi-account OAuth → check `oauthlib`, `authlib`, `social-auth-app-django` patterns.
- Email triage → check `notmuch`, `afew`, `mailpile` for tagging conventions.
- Calendar sync → check `google-calendar-cli`, `khal`, `etesync` for incremental-sync patterns.
- Voice intent routing → check `rasa`, `snips-nlu`, `picovoice rhino` for intent classification.
- Wake word → check `openwakeword`, `porcupine`, `precise` (already harvested).
- TTS providers → check `coqui-tts`, `bark`, `piper`, `mozilla-tts`.

If a feature has been built 100 times before in open source, our value-add is integration + UX, not reinvention.

## SEARCH BEFORE EXPLORING (MANDATORY)

Before using Glob/Grep to explore the codebase, use QMD MCP tools for documentation lookup:

- `qmd_search "keyword query"` - Fast BM25 keyword search across all project .md docs
- `qmd_vsearch "conceptual query"` - Semantic search by meaning (e.g., "how does auth work")
- `qmd_query "complex question"` - Hybrid BM25 + vector + LLM re-ranking (best quality, slower)
- `qmd_get "path/to/file.md"` - Retrieve full document content
- `qmd_multi_get "docs/product/*.md"` - Retrieve multiple docs by pattern

**When to use which tool:**
- **QMD**: Finding docs about "how does X work", "what's the pattern for Y", discovering relevant guides
- **Direct Read**: When you know the exact file path from the Module Map in MEMORY.md
- **Glob/Grep**: When searching .py/.tsx source code (QMD only indexes .md files)

## Proactive Monitoring

When starting a session or checking the system:
1. `docker ps --format "table {{.Names}}\t{{.Status}}"`
2. `docker logs --tail 100 zero-gateway 2>&1 | grep -i "error\|fail\|warn"`
3. Report and fix any issues before proceeding

## Common Issues
- **No response**: Check auth-profiles.json exists and shared-litellm + vllm-chat are healthy (`curl http://localhost:4444/health/liveliness`, `curl http://localhost:18800/v1/models`)
- **WhatsApp disconnected**: `docker exec -it zero-gateway node dist/index.js configure --section channels`
- **API 500 errors**: Check `docker logs zero-api` for tracebacks
- **Frontend not loading**: Verify zero-api is running on port 18792
