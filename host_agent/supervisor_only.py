r"""
Standalone minimal FastAPI app exposing only the daemon supervisor routes.

Intended for cases where host_agent's full ``main:app`` (which pulls in
sounddevice/pyaudio/whisper at import time) is slow to start or blocks on
hardware enumeration. This lets the DaemonPanel UI work while we diagnose the
audio stack separately. Audio/meeting features aren't available here — only
/daemon/*.

Run:
    ("C:\Users\hadam\AppData\Local\Reachy Mini Control\.venv\Scripts\python.exe"
     -u -m uvicorn supervisor_only:app --host 0.0.0.0 --port 18796)
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware

from supervisor import get_supervisor


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await get_supervisor().start_watchdog_if_enabled()
    except Exception:
        pass
    yield
    try:
        sup = get_supervisor()
        if sup.is_running():
            await sup.stop()
    except Exception:
        pass


app = FastAPI(title="Zero Host Agent Supervisor", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class WatchdogRequest(BaseModel):
    enabled: bool


@app.get("/health")
async def health():
    return {"ok": True, "mode": "supervisor_only"}


@app.get("/daemon/status")
async def daemon_status():
    return get_supervisor().status()


@app.post("/daemon/start")
async def daemon_start():
    try:
        return await get_supervisor().start()
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/daemon/stop")
async def daemon_stop():
    return await get_supervisor().stop()


@app.post("/daemon/restart")
async def daemon_restart():
    try:
        return await get_supervisor().restart(reason="manual")
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/daemon/logs")
async def daemon_logs(tail: int = 100):
    return get_supervisor().logs(tail=tail)


@app.get("/daemon/issues")
async def daemon_issues():
    return get_supervisor().known_issues()


@app.get("/daemon/diagnostics")
async def daemon_diagnostics():
    return await get_supervisor().diagnostics()


@app.post("/daemon/audio/reset")
async def daemon_audio_reset():
    return await get_supervisor().reset_audio()


@app.get("/daemon/watchdog")
async def daemon_watchdog_status():
    return get_supervisor().watchdog_info()


@app.post("/daemon/watchdog")
async def daemon_watchdog_set(request: WatchdogRequest):
    return await get_supervisor().set_watchdog(request.enabled)
