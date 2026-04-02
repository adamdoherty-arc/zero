"""
ZERO API - FastAPI Backend

Personal AI Assistant API providing sprint management, task tracking,
knowledge management, and agent orchestration.
"""

import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import structlog


from app.routers import (
    sprints, tasks, orchestrator, enhancements, projects, knowledge,
    audio, email, calendar, assistant, money_maker, workflows,
    system, research, ecosystem, google_oauth, qa, notion, agent, engine,
    gpu, llm, chat, research_rules, tiktok_shop, tiktok_content, content_agent,
    prediction_markets, llc_guidance, approvals, visual_workflows,
    meetings, meeting_recordings, meeting_transcriptions, meeting_summaries,
    meeting_chat, meeting_search, meeting_speakers, meeting_ws,
    ecosystem_health,
    tts, reachy,
    feedback, goals, memory,
    vision, focus,
)
from app.infrastructure.config import get_settings
from app.infrastructure.exceptions import register_exception_handlers
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Set root logger to INFO so structlog filter_by_level passes INFO+ messages
import logging
logging.basicConfig(format="%(message)s", level=logging.INFO)

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.dev.ConsoleRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("Starting ZERO API")
    settings = get_settings()
    logger.info("Configuration loaded", workspace=settings.workspace_dir)

    # Initialize PostgreSQL database
    from app.infrastructure.database import init_database, close_database, create_tables
    import app.db.models  # noqa: F401 — register ORM models with Base.metadata
    try:
        await init_database(settings.postgres_url)
        await create_tables()
        logger.info("Database initialized")

        # Seed knowledge categories and research rules
        try:
            from app.services.knowledge_service import get_knowledge_service
            from app.services.research_rules_service import get_research_rules_service
            ks = get_knowledge_service()
            cats_created = await ks.seed_default_categories()
            if cats_created:
                logger.info("Seeded knowledge categories", count=cats_created)
            rules_created = await get_research_rules_service().seed_default_rules()
            if rules_created:
                logger.info("Seeded research rules", count=rules_created)
        except Exception as e:
            logger.warning("Failed to seed defaults", error=str(e))
    except Exception as e:
        logger.error("Failed to initialize database", error=str(e))

    # Ensure recordings directory exists
    from app.infrastructure.config import get_recordings_path
    recordings_path = get_recordings_path()
    recordings_path.mkdir(parents=True, exist_ok=True)
    logger.info("Recordings directory ready", path=str(recordings_path))

    # Initialize centralized LLM router (must happen before startup checks)
    from app.infrastructure.llm_router import get_llm_router
    await get_llm_router().initialize()

    # Run startup validation checks
    from app.infrastructure.startup import run_startup_checks
    checks_passed = await run_startup_checks()
    if not checks_passed:
        logger.error("CRITICAL: Startup checks failed — some features may not work correctly")

    # Start the daily automation scheduler
    try:
        from app.services.scheduler_service import start_scheduler, stop_scheduler
        await start_scheduler()
        logger.info("Daily automation scheduler started")
    except Exception as e:
        logger.warning("Failed to start scheduler", error=str(e))

    # Start Discord bot (Claude Agent SDK messaging bridge)
    # NOTE: The bot uses claude-agent-sdk which requires the `claude` CLI binary.
    # With the Max plan, auth is handled by the local Claude Code installation.
    # In Docker, `claude` CLI isn't available — run the bot standalone on the host:
    #   cd backend && python -m app.services.discord_bot
    discord_task = None
    try:
        import shutil
        claude_available = shutil.which("claude") is not None
        from app.services.discord_bot import start_bot, stop_bot, BOT_TOKEN
        if not BOT_TOKEN:
            logger.info("discord_bot_disabled", reason="DISCORD_BOT_TOKEN not set")
        elif not claude_available:
            logger.info("discord_bot_skipped",
                        reason="claude CLI not found (run standalone on host: python -m app.services.discord_bot)")
        else:
            discord_task = asyncio.create_task(start_bot(), name="discord_bot")

            def _discord_done(task: asyncio.Task):
                if task.cancelled():
                    logger.info("discord_bot_cancelled")
                elif task.exception():
                    logger.error("discord_bot_crashed", error=str(task.exception()))
                else:
                    logger.info("discord_bot_stopped_cleanly")

            discord_task.add_done_callback(_discord_done)
            logger.info("discord_bot_starting")
    except Exception as e:
        logger.warning("discord_bot_import_failed", error=str(e))

    # Register graceful shutdown
    import signal
    _shutting_down = False

    async def graceful_shutdown():
        nonlocal _shutting_down
        if _shutting_down:
            return
        _shutting_down = True
        logger.info("Graceful shutdown initiated")

        # Stop scheduler (waits for in-flight jobs up to 30s)
        try:
            from app.services.scheduler_service import stop_scheduler
            await stop_scheduler()
            logger.info("Scheduler stopped")
        except Exception as e:
            logger.warning("Failed to stop scheduler", error=str(e))

        # Stop Discord bot
        try:
            from app.services.discord_bot import stop_bot
            await stop_bot()
            logger.info("Discord bot stopped")
        except Exception:
            pass

        # Close shared Ollama client
        try:
            from app.infrastructure.ollama_client import get_ollama_client
            await get_ollama_client().close()
        except Exception:
            pass

        # Close database connections
        try:
            await close_database()
        except Exception:
            pass

        logger.info("Graceful shutdown complete")

    try:
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(graceful_shutdown()))
    except (NotImplementedError, AttributeError):
        # Windows doesn't support add_signal_handler
        pass

    yield

    # Normal shutdown path (lifespan exit)
    await graceful_shutdown()


app = FastAPI(
    title="ZERO API",
    description="Personal AI Assistant - Sprint management, task tracking, knowledge management, and agent orchestration",
    version="1.0.0",
    lifespan=lifespan,
)

# Rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Register global exception handlers
register_exception_handlers(app)

# CORS configuration for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5175", "http://localhost:3000", "http://127.0.0.1:5173", "http://127.0.0.1:5175"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(sprints.router, prefix="/api/sprints", tags=["Sprints"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["Tasks"])
app.include_router(projects.router, prefix="/api/projects", tags=["Projects"])
app.include_router(orchestrator.router, prefix="/api/orchestrator", tags=["Orchestrator"])
app.include_router(enhancements.router, prefix="/api/enhancements", tags=["Enhancements"])
app.include_router(knowledge.router, prefix="/api/knowledge", tags=["Knowledge"])
app.include_router(audio.router, prefix="/api/audio", tags=["Audio"])
app.include_router(email.router, prefix="/api/email", tags=["Email"])
app.include_router(calendar.router, prefix="/api/calendar", tags=["Calendar"])
app.include_router(google_oauth.router, prefix="/api/google", tags=["Google OAuth"])
app.include_router(assistant.router, prefix="/api/assistant", tags=["Assistant"])
app.include_router(money_maker.router, prefix="/api/money-maker", tags=["Money Maker"])
app.include_router(workflows.router, prefix="/api/workflows", tags=["Workflows"])
app.include_router(system.router, prefix="/api/system", tags=["System"])
app.include_router(research.router, prefix="/api/research", tags=["Research"])
app.include_router(ecosystem.router, prefix="/api/ecosystem", tags=["Ecosystem"])
app.include_router(ecosystem_health.router, prefix="/api/ecosystem/health", tags=["Ecosystem Health"])
app.include_router(qa.router, prefix="/api/qa", tags=["QA Verification"])
app.include_router(notion.router, prefix="/api/notion", tags=["Notion"])
app.include_router(agent.router, prefix="/api/agent", tags=["Agent"])
app.include_router(engine.router, prefix="/api/engine", tags=["Enhancement Engine"])
app.include_router(gpu.router, prefix="/api/gpu", tags=["GPU Management"])
app.include_router(llm.router, prefix="/api/llm", tags=["LLM Router"])
app.include_router(chat.router, prefix="/api/ask-zero", tags=["Ask Zero"])
app.include_router(research_rules.router, tags=["Research Rules"])
app.include_router(tiktok_shop.router, prefix="/api/tiktok-shop", tags=["TikTok Shop"])
app.include_router(tiktok_content.router, prefix="/api/tiktok-content", tags=["TikTok Content"])
app.include_router(content_agent.router, prefix="/api/content-agent", tags=["Content Agent"])
app.include_router(prediction_markets.router, prefix="/api/prediction-markets", tags=["Prediction Markets"])
app.include_router(llc_guidance.router, prefix="/api/llc-guidance", tags=["LLC Guidance"])
app.include_router(approvals.router, prefix="/api/approvals", tags=["Approvals"])
app.include_router(visual_workflows.router, prefix="/api/visual-workflows", tags=["Visual Workflows"])

# Text-to-Speech & Reachy Mini Robot
app.include_router(tts.router, prefix="/api/tts", tags=["Text-to-Speech"])
app.include_router(reachy.router, prefix="/api/reachy", tags=["Reachy Mini Robot"])

# Meeting Intelligence (DailyMemory)
app.include_router(meetings.router, prefix="/api/meetings", tags=["Meetings"])
app.include_router(meeting_recordings.router, prefix="/api/meeting-recordings", tags=["Meeting Recordings"])
app.include_router(meeting_transcriptions.router, prefix="/api/meeting-transcriptions", tags=["Meeting Transcriptions"])
app.include_router(meeting_summaries.router, prefix="/api/meeting-summaries", tags=["Meeting Summaries"])
app.include_router(meeting_chat.router, prefix="/api/meeting-chat", tags=["Meeting Chat"])
app.include_router(meeting_search.router, prefix="/api/meeting-search", tags=["Meeting Search"])
app.include_router(meeting_speakers.router, prefix="/api/meetings", tags=["Meeting Speakers"])
app.include_router(meeting_ws.router, tags=["Meeting WebSockets"])

# Personal Assistant (feedback, goals, memory)
app.include_router(feedback.router, prefix="/api/feedback", tags=["Feedback"])
app.include_router(goals.router, prefix="/api/goals", tags=["Goals"])
app.include_router(memory.router, prefix="/api/memory", tags=["Memory"])

# Vision & Cross-Domain Focus
app.include_router(vision.router, prefix="/api/vision", tags=["Vision"])
app.include_router(focus.router, prefix="/api/focus", tags=["Focus"])


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "ZERO API",
        "version": "1.0.0"
    }


@app.get("/health")
async def health():
    """Detailed health check."""
    from pathlib import Path
    settings = get_settings()
    workspace = Path(settings.workspace_dir).resolve()

    return {
        "status": "healthy",
        "components": {
            "api": "ok",
            "storage": "ok" if workspace.exists() else "missing",
        }
    }


@app.get("/health/live")
async def health_live():
    """Liveness probe — process is running."""
    return {"alive": True}


@app.get("/health/ready")
async def health_ready():
    """
    Readiness probe — checks critical dependencies.
    Used by Docker health checks to determine if container is healthy.
    Returns 503 if any critical dependency is down.
    """
    from datetime import datetime
    from pathlib import Path
    from fastapi.responses import JSONResponse

    checks = {}
    is_ready = True
    settings = get_settings()

    # Check storage
    workspace = Path(settings.workspace_dir).resolve()
    checks["storage"] = "ok" if workspace.exists() and workspace.is_dir() else "missing"
    if checks["storage"] != "ok":
        is_ready = False

    # Check scheduler
    try:
        from app.services.scheduler_service import get_scheduler_service
        scheduler = get_scheduler_service()
        checks["scheduler"] = "ok" if scheduler._running else "stopped"
    except Exception:
        checks["scheduler"] = "error"

    # Check Ollama (non-blocking, 2s timeout)
    try:
        import httpx
        base = settings.ollama_base_url.replace("/v1", "")
        async with httpx.AsyncClient(timeout=2) as client:
            resp = await client.get(f"{base}/api/tags")
            checks["ollama"] = "ok" if resp.status_code == 200 else "degraded"
    except Exception:
        checks["ollama"] = "unavailable"

    # Check Legion (non-blocking, 2s timeout)
    try:
        import httpx
        async with httpx.AsyncClient(timeout=2) as client:
            resp = await client.get(f"{settings.legion_api_url}/health")
            checks["legion"] = "ok" if resp.status_code == 200 else "degraded"
    except Exception:
        checks["legion"] = "unavailable"

    # Check SearXNG (non-blocking, 2s timeout — try both health endpoints)
    try:
        import httpx
        async with httpx.AsyncClient(timeout=2) as client:
            # Try /healthz first, fall back to /status
            for path in ["/healthz", "/status"]:
                try:
                    resp = await client.get(f"{settings.searxng_url}{path}")
                    if resp.status_code == 200:
                        checks["searxng"] = "ok"
                        break
                except Exception:
                    continue
            else:
                checks["searxng"] = "degraded"
    except Exception:
        checks["searxng"] = "unavailable"

    status_code = 200 if is_ready else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "ready": is_ready,
            "checks": checks,
            "timestamp": datetime.utcnow().isoformat(),
        }
    )
