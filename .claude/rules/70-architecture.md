# 70 — Architecture (always loaded)

## Backend (Python)

- **Async everywhere**: All I/O uses `async/await`.
- **Service pattern**: Domain logic in `services/`, routers are thin wrappers around services.
- **Pydantic models**: All request/response validated.
- **Singletons**: Use `@lru_cache()` (e.g., `get_settings()`).
- **Error handling**: Raise `HTTPException`, log via `structlog`.

## Frontend (TypeScript)

- **Functional components**: Hooks-based, no class components.
- **React Query**: Query key factory pattern for cache.
- **Zustand**: Global state for sprints, tasks, board, loading.
- **TypeScript strict**: No `any` types.
- **TailwindCSS**: Utility-first, dark theme (`bg-gray-900`, indigo accent).
- **shadcn/ui**: Component library in `src/components/ui/`.

## API Design

- RESTful JSON endpoints.
- Query params for filtering (`sprint_id`, `status`, `limit`).
- `PATCH` for partial updates.
- `POST` for state transitions (`/start`, `/complete`, `/move`).

## Project structure

- **Backend** (`backend/`): FastAPI on `:18792`, container `zero-api`. Code is COPY'd; rebuild required.
- **Frontend** (`frontend/`): React 19 + Vite on `:5173`, container `zero-ui`. `src/` is volume-mounted.
- **Mobile PWA**: Installable surface at `/m/*` for Android/iOS. Routes in `frontend/src/App.tsx`, layout in `frontend/src/layouts/MobileLayout.tsx`, service worker in `frontend/src/sw.ts` (hand-authored `injectManifest`). Guide: `docs/mobile-pwa.md`.
- **Share Target**: `/share` consumes POSTs from the Android share sheet via the SW, forwards to `reference-videos/ingest-simple`.

## Robot/Reachy removal (2026-07-11)

Robot/Reachy hardware control (Cockpit, daemon, motion library, teleop, camera, realtime voice chat, mascot) was hard-deleted from Zero and moved to a separate app, **Zero Studio**. Zero has no voice or camera surface anymore — it's text/task-focused. Don't re-add `InteractiveModeBar`, `FloatingVoiceButton`, `LLMStatusBadge`, `ReachyCameraViewer`, or `host_agent` here.

## Daily Brief & Supervisor (2026-05-09)

- **Daily brief composer** runs at 07:00 server-local. Lands in the `/` dashboard tile (`DailyBrief` component) and is emailed when `ZERO_DAILY_BRIEF_TO` is set. Override hour with `ZERO_DAILY_BRIEF_HOUR/_MINUTE`; disable email-send with `ZERO_DAILY_BRIEF_EMAIL=0`.
- **Weekly reflection** runs Sundays 22:00 — drives closed-loop learning via the existing `reflection_service`.
- **Supervisor graph** at `backend/app/services/supervisor_graph.py` classifies user intent (calendar / email / company / bookkeeper / research / direct) and dispatches to the right handler. New agent-dispatch actions go here as `supervisor_graph` handlers, not as one-off router endpoints.
- **Email approval pool** at `/api/email/drafts/pool/*` — drafts land in a queue, you approve. UI at `/email/drafts`. **Don't** auto-send drafts; the pool is the trust boundary.

## Proactive monitoring

When starting a session:
1. `docker ps --format "table {{.Names}}\t{{.Status}}"`
2. `docker logs --tail 100 zero-gateway 2>&1 | grep -i "error\|fail\|warn"`
3. Report and fix any issues before proceeding.
