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
    prediction_markets,
)
from app.infrastructure.config import get_settings
from app.infrastructure.exceptions import register_exception_handlers

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
