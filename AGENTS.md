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

## Always use the latest model

**CRITICAL**: Before selecting any third-party LLM, vision, TTS, or embedding model, do a quick check for the current version. Providers ship faster than training data — the latest model at the time of *you writing this code* is probably not the latest when it runs. Current anchors (verify, don't cache):
- **Anthropic Codex**: Opus 4.7, Sonnet 4.6, Haiku 4.5.
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

## Reachy Self-Heal (three layers)

The Reachy stack stays up automatically across crashes, port collisions, and reboots:

1. **Reachy daemon (port 8000)** — supervised by host_agent. Enable with `POST http://localhost:18796/daemon/watchdog {"enabled":true}`. Polls every 10s; restarts the daemon process after 6 consecutive failures. State at [host_agent/supervisor.py](host_agent/supervisor.py).
2. **host_agent (port 18796)** — supervised by [host_agent/auto-restart.bat](host_agent/auto-restart.bat), an infinite loop wrapper that relaunches uvicorn after 5s if it exits. Uvicorn runs under `pythonw.exe` via `start /B /WAIT` so a `CTRL_CLOSE_EVENT` on the wrapper console does NOT propagate (the bare-`python.exe` form took host_agent down on 2026-04-25/26/27 via the Fortran-runtime window-CLOSE abort). Logs to `host_agent/logs/auto-restart.log`.
3. **Boot persistence** — Windows Scheduled Task `ZeroHostAgent` runs `auto-restart.bat` at user logon, wrapped in `powershell.exe -WindowStyle Hidden` so no console window exists at all (and thus no close-event can be sent). 999 restart attempts at 1-minute intervals on failure, `MultipleInstances=IgnoreNew`. Registered via [host_agent/register-autostart.ps1](host_agent/register-autostart.ps1).

**Docker stack** (zero-api, zero-ui, zero-searxng) uses `restart: unless-stopped` — survives docker daemon restarts but not host reboots without docker autostart.

**Operate the self-heal:**
```powershell
# Verify task exists
Get-ScheduledTask -TaskName ZeroHostAgent
# Run task immediately (e.g., after killing host_agent for testing)
Start-ScheduledTask -TaskName ZeroHostAgent
# Tail wrapper log
Get-Content c:\code\zero\host_agent\logs\auto-restart.log -Tail 20 -Wait
# Tail daemon log
Get-Content c:\code\zero\host_agent\logs\reachy-daemon-$(Get-Date -Format yyyyMMdd).log -Tail 20 -Wait
# Re-register / repair the task
powershell.exe -ExecutionPolicy Bypass -File c:\code\zero\host_agent\register-autostart.ps1
```

**If you change anything in this stack** (ports, supervisor, watchdog logic, wrapper script), re-run `register-autostart.ps1` and verify with `Get-ScheduledTask`. Never silently disable the watchdog — that's how Reachy went dark for 24 hours on 2026-04-24.

## Reachy Voice UX (do not undo)

- **Interactive Mode = primary voice surface**. `InteractiveModeBar` in the TopBar is the one-click live-conversation toggle (OpenAI Realtime / Gemini Live WebSocket). Space toggles, Esc ends. 5-min idle auto-off for cost safety.
- **FloatingVoiceButton is classic push-to-talk only** — do NOT re-add realtime auto-promote. Running two WebSocket instances = double billing.
- **LLMStatusBadge** in the TopBar is how the user picks/sees the active brain. Green/amber/red dots come from `GET /api/reachy-intent/providers/status` (1-token probes, 15 s cache, 5 s per-provider timeout).
- **Kimi K2.5/K2.6 require `temperature=1` EXACTLY**. `kimi_provider.py` clamps this for any `kimi-k2*` model. Don't pass other temps.

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
