"""
ZERO API - FastAPI Backend

Personal AI Assistant API providing sprint management, task tracking,
knowledge management, and agent orchestration.
"""

import asyncio
import os
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import structlog


from app.routers import (
    sprints, tasks, orchestrator, enhancements, projects, knowledge,
    audio, email, calendar, assistant, money_maker, workflows,
    system, research, ecosystem, google_oauth, qa, notion, agent, engine,
    gpu, llm, chat, research_rules, tiktok_shop, tiktok_content, content_agent,
    # prediction_markets — REMOVED 2026-05-18 (S2.5). ADA's Unusual Whales
    # pipeline is the sole SoT for whale / options-flow / prediction data.
    llc_guidance, approvals, visual_workflows,
    ecosystem_health,
    tts, oauth_accounts, sight,
    feedback, goals, memory,
    vision, focus,
    email_drafts, routine,
    habits, journal,
    agent_company, deep_research, experiments, council,
    autonomous_research, vault, agent_approvals, company_operator, company_work_items, company_facts,
    assets, tax_summary,
    personal_work_items,
    character_content, brain,
    character_reference_videos,
    media_content,
    content_control,
    trend_intelligence,
    employee,
    meals,
    loops,
    skills_proxy,
    bookkeeper,
    bookkeeper_agent,
    daily_brief,
    turn_outcomes,
    memory_tree,
    integrations,
    triggers,
    subconscious,
    skill_registry,
    browser_control,
    telegram_channel,
    openhands,
    notifications,
    zero_run,
    reels,
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
    import app.db.models  # noqa: F401 â€” register ORM models with Base.metadata
    try:
        await init_database(settings.postgres_url)
        await create_tables()
        logger.info("Database initialized")

        # Recover any loop_runs that were left in 'running' state by a previous
        # container that exited mid-dispatch. asyncio tasks die with the
        # process, so any in-flight skill execution is lost on restart.
        try:
            from app.infrastructure.database import get_session
            from app.db.models import LoopRunModel
            from sqlalchemy import update
            from datetime import datetime, timezone, timedelta
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=2)
            async with get_session() as session:
                result = await session.execute(
                    update(LoopRunModel)
                    .where(LoopRunModel.status == "running")
                    .where(LoopRunModel.started_at < cutoff)
                    .values(
                        status="failure",
                        ended_at=datetime.now(timezone.utc),
                        error="orphaned by container restart",
                    )
                )
                if result.rowcount:
                    logger.warning("loop_runs.orphans_recovered", count=result.rowcount)
                await session.commit()
        except Exception as e:
            logger.warning("loop_runs.orphan_recovery_failed", error=str(e))

        try:
            from app.services.company_work_item_service import ensure_company_work_item_schema
            await ensure_company_work_item_schema()
            logger.info("Company work-item schema verified")
        except Exception as e:
            logger.warning("Failed to verify company work-item schema", error=str(e))

        try:
            from app.services.personal_work_item_service import ensure_personal_project_indexes
            await ensure_personal_project_indexes()
            logger.info("Personal work-item indexes verified")
        except Exception as e:
            logger.warning("Failed to verify personal work-item indexes", error=str(e))

        # Fix-110: re-assert vault search-infra (content_tsv + GIN/HNSW) every
        # startup so the Fix-109 silent-500 class (ORM create_all drops
        # migration-only objects while alembic stays ahead) can never recur.
        try:
            from app.services.vault_retrieval_service import ensure_vault_search_infra
            _vsi = await ensure_vault_search_infra()
            if _vsi.get("healed"):
                logger.warning(
                    "vault_search_infra_healed_at_startup",
                    missing=_vsi.get("missing_before"),
                )
            else:
                logger.info("Vault search-infra verified")
        except Exception as e:
            logger.warning("Failed to verify vault search-infra", error=str(e))

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

            # Seed baseline character-content prompt variants so Thompson
            # Sampling has a starting point and every instrumented LLM call
            # can be tagged with a variant_id.
            try:
                from app.services.content_production_control_service import (
                    get_content_production_control_service,
                )

                if await get_content_production_control_service().is_paused():
                    logger.warning("character_prompt_seed_skipped_content_production_paused")
                else:
                    from app.services.character_prompt_seeds import (
                        seed_character_prompt_variants,
                        seed_carousel_v2_rhythm_variant,
                    )
                    seed_summary = await seed_character_prompt_variants()
                    if seed_summary.get("inserted"):
                        logger.info("Seeded character prompt variants", **seed_summary)
                    # Idempotently install the rhythm-spec carousel prompt and
                    # retire any older arms for the same task type.
                    v2_summary = await seed_carousel_v2_rhythm_variant()
                    if v2_summary.get("action") == "registered":
                        logger.info("Registered carousel_v2_rhythm variant", **v2_summary)
            except Exception as e:
                logger.warning("Failed to seed character prompt variants", error=str(e))

            # Seed meal services catalog (CookUnity, Factor, HelloFresh, etc.)
            try:
                from app.services.meal_catalog_service import get_meal_catalog_service
                meals_added = await get_meal_catalog_service().seed_defaults()
                if meals_added:
                    logger.info("Seeded meal services", count=meals_added)
            except Exception as e:
                logger.warning("Failed to seed meal services", error=str(e))
        except Exception as e:
            logger.warning("Failed to seed defaults", error=str(e))
    except Exception as e:
        logger.error("Failed to initialize database", error=str(e))

    # Ensure recordings directory exists
    from app.infrastructure.config import get_recordings_path
    recordings_path = get_recordings_path()
    recordings_path.mkdir(parents=True, exist_ok=True)
    logger.info("Recordings directory ready", path=str(recordings_path))

    # Ensure character reference videos directory exists
    from pathlib import Path as _Path
    cref_dir = _Path("workspace") / "character_content" / "reference_videos"
    cref_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Character reference videos directory ready", path=str(cref_dir))

    # Initialize centralized LLM router (must happen before startup checks)
    from app.infrastructure.llm_router import get_llm_router
    await get_llm_router().initialize()

    # Run startup validation checks
    from app.infrastructure.startup import run_startup_checks
    checks_passed = await run_startup_checks()
    if not checks_passed:
        logger.error("CRITICAL: Startup checks failed â€” some features may not work correctly")

    # Start the daily automation scheduler (skip in research mode to prevent conflicts)
    research_mode = os.environ.get("ZERO_RESEARCH_MODE", "").lower() in ("1", "true", "yes")
    if research_mode:
        logger.info("scheduler_skipped_research_mode")
    else:
        try:
            from app.services.scheduler_service import start_scheduler, stop_scheduler
            await start_scheduler()
            from app.services.content_production_control_service import (
                get_content_production_control_service,
            )
            sync_result = await (
                get_content_production_control_service().sync_scheduler_with_policy()
            )
            if sync_result.get("synced"):
                logger.warning(
                    "content_production_freeze_synced_on_startup",
                    result=sync_result,
                )
            logger.info("Daily automation scheduler started")
        except Exception as e:
            logger.warning("Failed to start scheduler", error=str(e))

        # Integrations auto-fetch loop (20-min walk over every connected
        # service â†’ Memory Vault). Off by default; ZERO_AUTO_FETCH_AUTOSTART=1
        # to enable on every boot, or hit /api/integrations/auto-fetch/start.
        try:
            if os.environ.get("ZERO_AUTO_FETCH_AUTOSTART", "").lower() in ("1", "true"):
                from app.services.integrations import get_auto_fetch_loop
                await get_auto_fetch_loop().start()
                logger.info("auto_fetch_autostart_enabled")
        except Exception as e:
            logger.warning("auto_fetch_autostart_failed", error=str(e))

        # Subconscious idle reflection. Same toggle pattern.
        try:
            if os.environ.get("ZERO_SUBCONSCIOUS_AUTOSTART", "").lower() in ("1", "true"):
                from app.services.subconscious_loop import get_subconscious_loop
                await get_subconscious_loop().start()
                logger.info("subconscious_autostart_enabled")
        except Exception as e:
            logger.warning("subconscious_autostart_failed", error=str(e))

        # Telegram channel â€” starts itself iff TELEGRAM_BOT_TOKEN is set.
        # Default handler writes inbound messages to the Memory Vault.
        try:
            from app.services.telegram_channel_service import (
                get_telegram_channel_service,
            )
            tg = get_telegram_channel_service()
            if tg.is_configured():
                await tg.start()
                logger.info("telegram_channel_started")
        except Exception as e:
            logger.warning("telegram_channel_start_failed", error=str(e))

        # Daily brief â€” composes the morning report and emails it. Runs at
        # 07:00 server-local time. Hour overridable via ZERO_DAILY_BRIEF_HOUR.
        try:
            from app.services.scheduler_service import get_scheduler_service
            from app.services.daily_brief_service import get_daily_brief_service
            from app.services.digest_email_service import get_digest_email_service
            sched = get_scheduler_service().scheduler
            brief_hour = int(os.environ.get("ZERO_DAILY_BRIEF_HOUR", "7"))
            brief_minute = int(os.environ.get("ZERO_DAILY_BRIEF_MINUTE", "0"))

            async def _daily_brief_job() -> None:
                try:
                    payload = await get_daily_brief_service().compose_today()
                    if os.environ.get("ZERO_DAILY_BRIEF_EMAIL", "1") not in ("0", "false", "no"):
                        await get_digest_email_service().send(
                            markdown=payload.markdown,
                            subject=f"Daily brief â€” {payload.date}",
                        )
                except Exception as exc:
                    logger.warning("daily_brief_job_failed", error=str(exc))

            sched.add_job(
                _daily_brief_job,
                trigger="cron",
                hour=brief_hour,
                minute=brief_minute,
                id="daily_brief_morning",
                name="Daily brief composer + emailer",
                replace_existing=True,
            )
            logger.info(
                "Daily brief scheduled",
                hour=brief_hour, minute=brief_minute,
            )
        except Exception as e:
            logger.warning("Failed to schedule daily brief", error=str(e))

        # Weekly reflection â€” drives the closed-loop learning. Sunday 22:00.
        try:
            from app.services.scheduler_service import get_scheduler_service
            sched = get_scheduler_service().scheduler

            async def _weekly_reflection_job() -> None:
                # Fix-116: ReflectionService exposes reflect()/reflect_on_decisions(),
                # never run()/run_weekly() — so the old getattr probe always missed
                # and this Sunday job was a permanent silent no-op. Drive the real
                # closed-loop reflection entrypoint instead.
                try:
                    from app.services.zero_brain_service import get_zero_brain_service
                    result = await get_zero_brain_service().run_reflection()
                    logger.info("weekly_reflection_ran", result_keys=list((result or {}).keys()))
                except Exception as exc:
                    logger.warning("weekly_reflection_failed", error=str(exc))

            sched.add_job(
                _weekly_reflection_job,
                trigger="cron",
                day_of_week="sun",
                hour=22,
                minute=0,
                id="weekly_reflection",
                name="Closed-loop weekly reflection",
                replace_existing=True,
            )
            logger.info("Weekly reflection scheduled (Sun 22:00)")
        except Exception as e:
            logger.warning("Failed to schedule weekly reflection", error=str(e))

        # Reconcile persisted enabled-state across every job now registered,
        # including the ones added directly above (daily_brief_morning,
        # weekly_reflection). These register AFTER start_scheduler()
        # applied overrides, so without this pass a persisted disable — notably
        # the master "disable all" — would leak them back on after a restart.
        try:
            from app.services.scheduler_service import get_scheduler_service
            reconciled = get_scheduler_service().reconcile_enabled_state()
            if reconciled.get("paused") or reconciled.get("resumed"):
                logger.info("scheduler_enabled_state_reconciled", **reconciled)
        except Exception as e:
            logger.warning("scheduler_reconcile_failed", error=str(e))

    # Auto-resume character research queue from persisted state
    class _ContentProductionStartupSkip(Exception):
        pass

    try:
        from app.services.content_production_control_service import (
            get_content_production_control_service,
        )
        if await get_content_production_control_service().is_paused():
            logger.warning("auto_resume_research_skipped_content_production_paused")
            raise _ContentProductionStartupSkip()

        from app.services.character_content_service import (
            get_character_content_service, _research_queue,
        )
        from app.infrastructure.database import get_session
        from app.db.models import CharacterModel, ResearchQueueStateModel
        from app.models.character_content import ResearchJob, ResearchJobStep, ResearchJobStatus
        from sqlalchemy import select, func

        svc = get_character_content_service()

        # Check for persisted queue state (interrupted run)
        async with get_session() as session:
            queue_rows = (await session.execute(
                select(ResearchQueueStateModel)
                .order_by(ResearchQueueStateModel.queue_position)
            )).scalars().all()

        if queue_rows:
            # Rebuild in-memory queue from DB state
            logger.info("research_queue_resume_detected", count=len(queue_rows))
            step_names = [
                "searxng_search", "wiki_scrape", "deep_research",
                "synthesis", "fact_extraction", "image_sourcing", "save_results",
            ]

            _research_queue["jobs"] = {}
            _research_queue["order"] = []
            _research_queue["running"] = True
            _research_queue["cancel_requested"] = False
            _research_queue["started_at"] = datetime.now(timezone.utc).isoformat()

            for qrow in queue_rows:
                async with get_session() as session:
                    char = await session.get(CharacterModel, qrow.character_id)
                    if not char:
                        continue
                    char_completed = set(char.research_completed_steps or [])
                    # Mark character as researching
                    char.research_status = "researching"
                    await session.commit()

                steps = []
                for s in step_names:
                    status = "completed" if s in char_completed else "pending"
                    step = ResearchJobStep(name=s).model_dump()
                    step["status"] = status
                    steps.append(step)

                job_data = ResearchJob(
                    id=qrow.job_id,
                    character_id=qrow.character_id,
                    character_name=char.name,
                    universe=char.universe or "",
                    status=ResearchJobStatus.QUEUED,
                    steps=steps,
                ).model_dump()
                job_data["status"] = "queued"
                _research_queue["jobs"][qrow.job_id] = job_data
                _research_queue["order"].append(qrow.job_id)

            if _research_queue["order"]:
                asyncio.create_task(svc._run_research_queue())
                logger.info("research_queue_resumed",
                            jobs=len(_research_queue["order"]))
            else:
                _research_queue["running"] = False
        else:
            # No persisted queue; fall back to resetting stuck characters
            # and auto-starting if there are pending characters
            async with get_session() as session:
                from sqlalchemy import update as sa_update
                await session.execute(
                    sa_update(CharacterModel)
                    .where(CharacterModel.research_status == "researching")
                    .values(research_status="pending", research_completed_steps=[])
                )
                await session.commit()
                result = await session.execute(
                    select(func.count()).where(
                        CharacterModel.research_status.in_(["pending", "failed", "needs_retry"])
                    )
                )
                pending_count = result.scalar() or 0
            if pending_count > 0:
                logger.info("auto_start_research_queue", pending=pending_count)
                await svc.start_batch_research_async(limit=pending_count)
    except _ContentProductionStartupSkip:
        pass
    except Exception as e:
        logger.warning("auto_resume_research_failed", error=str(e))

    # Start Discord bot (Claude Agent SDK messaging bridge)
    # NOTE: The bot uses claude-agent-sdk which requires the `claude` CLI binary.
    # With the Max plan, auth is handled by the local Claude Code installation.
    # In Docker, `claude` CLI isn't available â€” run the bot standalone on the host:
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

    # S5 + S23 (2026-05-18): Zero → Legion heartbeat emitter. Posts cpu/mem/
    # active-agents to /api/projects/{id}/heartbeat every 30s so Legion's
    # S9 dashboard + S20 health score have a fresh signal. Fire-and-forget:
    # any failure is logged but never raised into Zero's main loop.
    try:
        from app.services.legion_heartbeat_emitter import start_heartbeat_loop
        asyncio.create_task(start_heartbeat_loop(), name="legion_heartbeat")
        logger.info("legion_heartbeat_emitter_started")
    except Exception as _hb_exc:
        logger.warning("legion_heartbeat_emitter_failed", error=str(_hb_exc)[:200])

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

        # Stop integrations auto-fetch + subconscious loops.
        try:
            from app.services.integrations import get_auto_fetch_loop
            await get_auto_fetch_loop().stop()
        except Exception:
            pass
        try:
            from app.services.subconscious_loop import get_subconscious_loop
            await get_subconscious_loop().stop()
        except Exception:
            pass
        try:
            from app.services.telegram_channel_service import (
                get_telegram_channel_service,
            )
            await get_telegram_channel_service().stop()
        except Exception:
            pass

        # Close shared Ollama client
        try:
            from app.infrastructure.ollama_client import get_llm_client
            await get_llm_client().close()
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


CONTENT_PRODUCTION_WRITE_PREFIXES = ("/api/characters", "/api/media-content")
CONTENT_PRODUCTION_WRITE_METHODS = {"POST", "PATCH", "DELETE"}
CONTENT_PRODUCTION_WRITE_ALLOWLIST = {
    "/api/characters/research-queue/cancel",
}


@app.middleware("http")
async def content_production_hard_freeze_guard(request: Request, call_next):
    path = request.url.path
    if (
        request.method in CONTENT_PRODUCTION_WRITE_METHODS
        and path not in CONTENT_PRODUCTION_WRITE_ALLOWLIST
        and any(path.startswith(prefix) for prefix in CONTENT_PRODUCTION_WRITE_PREFIXES)
    ):
        from app.services.content_production_control_service import (
            get_content_production_control_service,
        )

        service = get_content_production_control_service()
        try:
            policy = await service.get_policy()
        except RuntimeError as exc:
            if "Database not initialized" not in str(exc):
                raise
            logger.warning(
                "content_production_freeze_guard_skipped",
                reason="database_not_initialized",
                path=path,
                method=request.method,
            )
            return await call_next(request)
        if policy.paused:
            return JSONResponse(
                status_code=423,
                content={
                    "error": {
                        "message": policy.reason,
                        "type": "ContentProductionPausedError",
                        "details": {
                            "action": f"{request.method} {path}",
                            "paused": True,
                        },
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                },
            )
    return await call_next(request)


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
app.include_router(oauth_accounts.router, prefix="/api/oauth/accounts", tags=["OAuth Accounts"])
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
app.include_router(meals.router, prefix="/api/meals", tags=["Meal Manager"])
app.include_router(tiktok_content.router, prefix="/api/tiktok-content", tags=["TikTok Content"])
app.include_router(content_agent.router, prefix="/api/content-agent", tags=["Content Agent"])
# prediction_markets router REMOVED 2026-05-18 (S2.5). ADA's Unusual Whales is the SoT.
# Restore from C:\code\Zero\.archive\2026-05-18-prediction-market-removal\ if needed.
app.include_router(llc_guidance.router, prefix="/api/llc-guidance", tags=["LLC Guidance"])
app.include_router(approvals.router, prefix="/api/approvals", tags=["Approvals"])
app.include_router(visual_workflows.router, prefix="/api/visual-workflows", tags=["Visual Workflows"])

# Text-to-Speech (reels narration, meeting confirmations) & wearable-agnostic vision
app.include_router(tts.router, prefix="/api/tts", tags=["Text-to-Speech"])
app.include_router(sight.router, prefix="/api/sight", tags=["Sight (wearable-agnostic vision)"])

# Meeting Intelligence removed from product 2026-06-20 (routers unmounted; code/tables kept dormant)

# Personal Assistant (feedback, goals, memory)
app.include_router(feedback.router, prefix="/api/feedback", tags=["Feedback"])
app.include_router(goals.router, prefix="/api/goals", tags=["Goals"])
app.include_router(memory.router, prefix="/api/memory", tags=["Memory"])

# Vision & Cross-Domain Focus
app.include_router(vision.router, prefix="/api/vision", tags=["Vision"])
app.include_router(focus.router, prefix="/api/focus", tags=["Focus"])

# Smart Email Drafting & Daily Routine
app.include_router(email_drafts.router, prefix="/api/email/drafts", tags=["Email Drafts"])
app.include_router(routine.router, prefix="/api/routine", tags=["Daily Routine"])

# Habit Tracking & Daily Journal
app.include_router(habits.router, prefix="/api/habits", tags=["Habits"])
app.include_router(journal.router, prefix="/api/journal", tags=["Journal"])

# AI Company
app.include_router(character_content.router, prefix="/api/characters", tags=["Character Content"])
app.include_router(
    character_reference_videos.router,
    prefix="/api/character-content/reference-videos",
    tags=["Character Reference Videos"],
)
app.include_router(
    character_reference_videos.file_router,
    prefix="/api/character-content/reference-videos",
    tags=["Character Reference Videos"],
)
app.include_router(media_content.router, prefix="/api/media-content", tags=["Media Content"])
app.include_router(content_control.router, prefix="/api/content-control", tags=["Content Control"])
app.include_router(agent_company.router)  # prefix in router
app.include_router(company_operator.router)  # prefix in router
app.include_router(company_work_items.router)  # prefix in router
app.include_router(company_facts.router)  # prefix in router
app.include_router(assets.router)  # prefix in router
app.include_router(tax_summary.router)  # prefix in router
app.include_router(personal_work_items.router)  # prefix in router
app.include_router(personal_work_items.file_router)  # prefix in router
app.include_router(deep_research.router)  # prefix in router
app.include_router(autonomous_research.router)  # prefix in router
app.include_router(vault.router)  # prefix in router
app.include_router(agent_approvals.router)  # prefix in router
app.include_router(experiments.router)  # prefix in router
app.include_router(council.router)  # prefix in router
app.include_router(brain.router)  # prefix in router
app.include_router(trend_intelligence.router)  # prefix in router
app.include_router(employee.router, prefix="/api/employee", tags=["Employee Check-in"])
app.include_router(loops.health_router)  # public watchdog liveness probe
app.include_router(loops.router)  # authenticated loop registry/control
app.include_router(skills_proxy.router)  # /api/skills/* and /api/teams/* proxied to Legion
app.include_router(bookkeeper.router, prefix="/api/bookkeeper", tags=["Bookkeeper (ADA AI)"])
app.include_router(bookkeeper_agent.router)  # prefix in router (/api/company/bookkeeper)
app.include_router(daily_brief.router, prefix="/api/daily-brief", tags=["Daily Brief"])
app.include_router(turn_outcomes.router, prefix="/api/turn-outcomes", tags=["Turn Outcomes"])
app.include_router(memory_tree.router, prefix="/api/memory-vault", tags=["Memory Vault"])
app.include_router(memory_tree.router, prefix="/api/memory-tree", tags=["Memory Tree (deprecated alias)"])
app.include_router(integrations.router, prefix="/api/integrations", tags=["Integrations"])
app.include_router(triggers.router, prefix="/api/triggers", tags=["Triggers"])
app.include_router(subconscious.router, prefix="/api/subconscious", tags=["Subconscious"])
app.include_router(skill_registry.router, prefix="/api/skills", tags=["Skills"])
app.include_router(browser_control.router, prefix="/api/browser-control", tags=["Browser Control"])
app.include_router(telegram_channel.router, prefix="/api/telegram", tags=["Telegram"])
app.include_router(openhands.router, prefix="/api", tags=["OpenHands"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["Notifications"])
# Zero Supervisor — /api/zero/run + /critic + /stack-facts (Migration 053)
app.include_router(zero_run.router)
# Motivation Reels — quote-driven video pipeline (migration 059)
app.include_router(reels.router, prefix="/api/reels", tags=["Motivation Reels"])


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
    """Liveness probe â€” process is running."""
    return {"alive": True}


@app.get("/health/ready")
async def health_ready():
    """
    Readiness probe â€” checks critical dependencies.
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

    # Check PostgreSQL connectivity (non-blocking: reports degraded but doesn't fail ready)
    try:
        from app.infrastructure.database import get_engine
        import asyncio
        engine = get_engine()
        async with engine.connect() as conn:
            await asyncio.wait_for(conn.execute(__import__("sqlalchemy").text("SELECT 1")), timeout=2.0)
        checks["postgres"] = "ok"
    except Exception:
        checks["postgres"] = "degraded"

    # Check scheduler
    try:
        from app.services.scheduler_service import get_scheduler_service
        scheduler = get_scheduler_service()
        checks["scheduler"] = "ok" if scheduler._running else "stopped"
    except Exception:
        checks["scheduler"] = "error"

    # Optional downstream probes (local_llm, legion, searxng) run CONCURRENTLY.
    # Run sequentially they serialized to ~13s worst case; the local_llm probe
    # in particular burned its full timeout whenever the robot/vLLM was OFF (a
    # supported state), dragging readiness past the Docker healthcheck window and
    # falsely marking the container unhealthy *because the robot is off* — a
    # robot-off-safe regression. All three are non-blocking: they report
    # degraded/unavailable but never flip is_ready.
    import httpx

    async def _check_local_llm() -> str:
        # Ollama was retired in favor of the shared Bifrost route; the brain path
        # is "is the Bifrost gateway reachable" (every LLM call routes through it).
        # Fix-117: the old probe GET {vllm_chat_url}/models WITH the virtual key,
        # which makes Bifrost enumerate every upstream provider (incl. the dead
        # gemini 401 / groq 429 lanes) and ReadTimeout at 2s -> the probe falsely
        # reported "unavailable" while the brain was actually serving via
        # vllm-local. Probe Bifrost's liveliness endpoint instead: 200 in ~10ms,
        # no virtual key needed, same gateway-reachability granularity as
        # _check_legion / _check_searxng.
        try:
            base = settings.vllm_chat_url.rstrip("/")
            if base.endswith("/v1"):
                base = base[: -len("/v1")]  # /v1 -> gateway root
            async with httpx.AsyncClient(timeout=2) as client:
                resp = await client.get(f"{base}/health/liveliness")
                return "ok" if resp.status_code == 200 else "degraded"
        except Exception:
            return "unavailable"

    async def _check_legion() -> str:
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                resp = await client.get(f"{settings.legion_api_url}/health")
                return "ok" if resp.status_code == 200 else "degraded"
        except Exception:
            return "unavailable"

    async def _check_searxng() -> str:
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                for path in ["/healthz", "/status"]:
                    try:
                        resp = await client.get(f"{settings.searxng_url}{path}")
                        if resp.status_code == 200:
                            return "ok"
                    except Exception:
                        continue
            return "degraded"
        except Exception:
            return "unavailable"

    async def _check_search_infra() -> str:
        # Fix-110: surface vault search-infra drift (content_tsv dropped by
        # create_all) without a restart. "critical" => BM25 vault search 500s.
        try:
            from app.services.vault_retrieval_service import search_infra_status
            return (await search_infra_status())["status"]  # ok|degraded|critical
        except Exception:
            return "unavailable"

    llm_res, legion_res, searxng_res, search_infra_res = await asyncio.gather(
        _check_local_llm(), _check_legion(), _check_searxng(), _check_search_infra()
    )
    checks["local_llm"] = llm_res
    checks["ollama"] = "retired"
    checks["legion"] = legion_res
    checks["searxng"] = searxng_res
    checks["search_infra"] = search_infra_res

    status_code = 200 if is_ready else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "ready": is_ready,
            "checks": checks,
            "timestamp": datetime.utcnow().isoformat(),
        }
    )
