"""
ZERO API - FastAPI Backend

Personal AI Assistant API providing sprint management, task tracking,
knowledge management, and agent orchestration.
"""

import asyncio
import os
from datetime import datetime, timezone

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
    meeting_chat, meeting_search, meeting_speakers, meeting_ws, voiceprints,
    meeting_preferences,
    ecosystem_health,
    tts, reachy, reachy_intent, reachy_email, reachy_realtime, reachy_memory, reachy_companion, home_assistant, oauth_accounts, sight,
    feedback, goals, memory,
    vision, focus,
    email_drafts, routine,
    habits, journal,
    agent_company, deep_research, experiments, council,
    autonomous_research, vault, agent_approvals, voice_bridge, company_operator, company_work_items,
    character_content, brain,
    character_reference_videos,
    media_content,
    trend_intelligence,
    employee,
    meals,
    loops,
    skills_proxy,
    bookkeeper,
    daily_brief,
    turn_outcomes,
    wake_presence,
    memory_tree,
    integrations,
    triggers,
    subconscious,
    meeting_agent,
    skill_registry,
    browser_control,
    telegram_channel,
    openhands,
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

    # Load Reachy voice-stack config (STT / TTS selections) and pre-warm the
    # Whisper + Piper models so the first voice turn doesn't pay a 9-10 s
    # cold start. Both warmups are background tasks â€” startup keeps moving if
    # either model is missing.
    try:
        from app.services.reachy_voice_config_service import get_reachy_voice_config
        voice_cfg = get_reachy_voice_config()
        await voice_cfg.load()

        async def _voice_warmup() -> None:
            try:
                from app.services.audio_service import get_audio_service
                from app.services.tts_service import get_tts_service
                await get_audio_service().warmup(voice_cfg.get_stt_model())
            except Exception as e:
                logger.warning("audio_warmup_failed", error=str(e))
            try:
                from app.services.tts_service import get_tts_service
                await get_tts_service().warmup()
            except Exception as e:
                logger.warning("tts_warmup_failed", error=str(e))

        asyncio.create_task(_voice_warmup(), name="voice_warmup")
    except Exception as e:
        logger.warning("reachy_voice_config_init_failed", error=str(e))

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
            logger.info("Daily automation scheduler started")
        except Exception as e:
            logger.warning("Failed to start scheduler", error=str(e))

        # Reachy Mini ambient-behaviour scheduler (Wave 5). Attaches its own
        # jobs to the main AsyncIOScheduler so there is no extra event loop.
        try:
            from app.services.reachy_presence_service import get_reachy_presence_service
            get_reachy_presence_service().start()
            logger.info("Reachy presence scheduler started")
        except Exception as e:
            logger.warning("Failed to start Reachy presence scheduler", error=str(e))

        # Validate that every persona's edge-tts voice is real. Logs warnings
        # for any bad voice so future persona additions don't break silently.
        try:
            import asyncio as _asyncio
            from app.services.reachy_personas import validate_persona_voices
            _asyncio.create_task(validate_persona_voices())
        except Exception as e:
            logger.debug("Persona voice validation skipped", error=str(e))

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

        # Cross-session memory compaction: re-extract durable notes from
        # recent turns and age out low-confidence unused ones every 6 h.
        try:
            from app.services.scheduler_service import get_scheduler_service
            from app.services.reachy_user_memory_service import (
                get_reachy_user_memory_service,
            )
            sched = get_scheduler_service().scheduler

            async def _reachy_memory_compact_job() -> None:
                try:
                    await get_reachy_user_memory_service().compact()
                except Exception as exc:
                    logger.debug("reachy_memory_compact_failed", error=str(exc))

            sched.add_job(
                _reachy_memory_compact_job,
                trigger="interval",
                hours=6,
                id="reachy_memory_compact",
                name="Reachy user memory compaction",
                replace_existing=True,
            )
            logger.info("Reachy memory compaction scheduled (every 6h)")
        except Exception as e:
            logger.warning("Failed to schedule Reachy memory compaction", error=str(e))

        # One-shot migration: pull existing user_memory.json _notes into the
        # new Letta-style human block. Idempotent â€” guarded by a flag inside
        # the store so it only runs the first time after the schema change.
        try:
            from app.services.reachy_memory_blocks import get_reachy_memory_blocks
            await get_reachy_memory_blocks().maybe_migrate_from_user_memory()
        except Exception as e:
            logger.debug("reachy_memory_blocks_migration_skipped", error=str(e))

        # Nightly personality synthesis: 02:30 daily, after the 02:15 drift
        # scan. Reads the last 24 h of turns + current blocks and updates the
        # human + relationship blocks; writes a snapshot to the vault.
        try:
            from app.services.reachy_personality_synthesis_service import (
                get_reachy_personality_synthesis_service,
            )
            from app.services.scheduler_service import get_scheduler_service
            sched = get_scheduler_service().scheduler

            async def _reachy_personality_synthesis_job() -> None:
                try:
                    await get_reachy_personality_synthesis_service().run()
                except Exception as exc:
                    logger.debug(
                        "reachy_personality_synthesis_failed",
                        error=str(exc),
                    )

            sched.add_job(
                _reachy_personality_synthesis_job,
                trigger="cron",
                hour=2,
                minute=30,
                id="reachy_personality_synthesis_tick",
                name="Reachy nightly personality synthesis",
                replace_existing=True,
            )
            logger.info("Reachy personality synthesis scheduled (02:30 daily)")
        except Exception as e:
            logger.warning(
                "Failed to schedule Reachy personality synthesis",
                error=str(e),
            )

        # Home Assistant â†’ Reachy gesture watcher (Wave 6). Inert when HA is
        # not configured or the gesture map is empty.
        try:
            from app.services.home_assistant_watcher import get_ha_watcher
            get_ha_watcher().start()
        except Exception as e:
            logger.warning("Failed to start HA gesture watcher", error=str(e))

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
                try:
                    from app.services.reflection_service import (
                        get_reflection_service,
                    )
                    svc = get_reflection_service()
                    runner = (
                        getattr(svc, "run_weekly", None)
                        or getattr(svc, "run", None)
                    )
                    if runner is None:
                        return
                    await runner()
                except Exception as exc:
                    logger.debug("weekly_reflection_failed", error=str(exc))

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

    # Auto-resume character research queue from persisted state
    try:
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
app.include_router(prediction_markets.router, prefix="/api/prediction-markets", tags=["Prediction Markets"])
app.include_router(llc_guidance.router, prefix="/api/llc-guidance", tags=["LLC Guidance"])
app.include_router(approvals.router, prefix="/api/approvals", tags=["Approvals"])
app.include_router(visual_workflows.router, prefix="/api/visual-workflows", tags=["Visual Workflows"])

# Text-to-Speech & Reachy Mini Robot
app.include_router(tts.router, prefix="/api/tts", tags=["Text-to-Speech"])
app.include_router(reachy.router, prefix="/api/reachy", tags=["Reachy Mini Robot"])
app.include_router(reachy_intent.router, prefix="/api/reachy-intent", tags=["Reachy Voice Intents"])
app.include_router(reachy_email.router, prefix="/api/reachy/email", tags=["Reachy Email Triage"])
app.include_router(reachy_realtime.router, prefix="/api/reachy/realtime", tags=["Reachy Realtime Voice"])
app.include_router(reachy_memory.router, prefix="/api/reachy/memory", tags=["Reachy Memory Blocks"])
app.include_router(reachy_companion.router, prefix="/api/reachy/companion", tags=["Reachy Companion"])
app.include_router(home_assistant.router, prefix="/api/home-assistant", tags=["Home Assistant"])
app.include_router(sight.router, prefix="/api/sight", tags=["Sight (wearable-agnostic vision)"])

# Meeting Intelligence (DailyMemory)
app.include_router(meetings.router, prefix="/api/meetings", tags=["Meetings"])
app.include_router(meeting_recordings.router, prefix="/api/meeting-recordings", tags=["Meeting Recordings"])
app.include_router(meeting_transcriptions.router, prefix="/api/meeting-transcriptions", tags=["Meeting Transcriptions"])
app.include_router(meeting_summaries.router, prefix="/api/meeting-summaries", tags=["Meeting Summaries"])
app.include_router(meeting_chat.router, prefix="/api/meeting-chat", tags=["Meeting Chat"])
app.include_router(meeting_search.router, prefix="/api/meeting-search", tags=["Meeting Search"])
app.include_router(meeting_speakers.router, prefix="/api/meetings", tags=["Meeting Speakers"])
app.include_router(meeting_ws.router, tags=["Meeting WebSockets"])
app.include_router(voiceprints.router, prefix="/api/voiceprints", tags=["Voiceprints"])
app.include_router(meeting_preferences.router, prefix="/api/meeting-preferences", tags=["Meeting Preferences"])

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
app.include_router(agent_company.router)  # prefix in router
app.include_router(company_operator.router)  # prefix in router
app.include_router(company_work_items.router)  # prefix in router
app.include_router(deep_research.router)  # prefix in router
app.include_router(autonomous_research.router)  # prefix in router
app.include_router(vault.router)  # prefix in router
app.include_router(agent_approvals.router)  # prefix in router
app.include_router(voice_bridge.router)  # prefix in router
app.include_router(experiments.router)  # prefix in router
app.include_router(council.router)  # prefix in router
app.include_router(brain.router)  # prefix in router
app.include_router(trend_intelligence.router)  # prefix in router
app.include_router(employee.router, prefix="/api/employee", tags=["Employee Check-in"])
app.include_router(loops.router)  # prefix + tags defined in router
app.include_router(skills_proxy.router)  # /api/skills/* and /api/teams/* proxied to Legion
app.include_router(bookkeeper.router, prefix="/api/bookkeeper", tags=["Bookkeeper (ADA AI)"])
app.include_router(daily_brief.router, prefix="/api/daily-brief", tags=["Daily Brief"])
app.include_router(turn_outcomes.router, prefix="/api/turn-outcomes", tags=["Turn Outcomes"])
app.include_router(wake_presence.router, prefix="/api/wake-presence", tags=["Wake & Presence"])
app.include_router(memory_tree.router, prefix="/api/memory-vault", tags=["Memory Vault"])
app.include_router(memory_tree.router, prefix="/api/memory-tree", tags=["Memory Tree (deprecated alias)"])
app.include_router(integrations.router, prefix="/api/integrations", tags=["Integrations"])
app.include_router(triggers.router, prefix="/api/triggers", tags=["Triggers"])
app.include_router(subconscious.router, prefix="/api/subconscious", tags=["Subconscious"])
app.include_router(meeting_agent.router, prefix="/api/meeting-agent", tags=["Meeting Agent"])
app.include_router(skill_registry.router, prefix="/api/skills", tags=["Skills"])
app.include_router(browser_control.router, prefix="/api/browser-control", tags=["Browser Control"])
app.include_router(telegram_channel.router, prefix="/api/telegram", tags=["Telegram"])
app.include_router(openhands.router, prefix="/api", tags=["OpenHands"])


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

    # Check scheduler
    try:
        from app.services.scheduler_service import get_scheduler_service
        scheduler = get_scheduler_service()
        checks["scheduler"] = "ok" if scheduler._running else "stopped"
    except Exception:
        checks["scheduler"] = "error"

    # Check local LLM router (non-blocking, 2s timeout). Ollama was retired
    # in favor of the shared LiteLLM/vLLM route, so keep the legacy key from
    # reporting a false outage.
    try:
        import httpx
        base = settings.vllm_chat_url.rstrip("/")
        headers = {}
        if settings.vllm_api_key:
            headers["Authorization"] = f"Bearer {settings.vllm_api_key}"
        async with httpx.AsyncClient(timeout=2) as client:
            resp = await client.get(f"{base}/models", headers=headers)
            checks["local_llm"] = "ok" if resp.status_code == 200 else "degraded"
    except Exception:
        checks["local_llm"] = "unavailable"
    checks["ollama"] = "retired"

    # Check Legion (non-blocking, 2s timeout)
    try:
        import httpx
        async with httpx.AsyncClient(timeout=2) as client:
            resp = await client.get(f"{settings.legion_api_url}/health")
            checks["legion"] = "ok" if resp.status_code == 200 else "degraded"
    except Exception:
        checks["legion"] = "unavailable"

    # Check SearXNG (non-blocking, 2s timeout â€” try both health endpoints)
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
