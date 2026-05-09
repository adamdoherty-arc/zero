# Carousels — 73.9/100

**Trend:** 80 → 73.9 (more carousels reviewed → exposes real Stage-2 variance)

## Issues
- None this window. (Stage 2 avg 7.39 is now above the 7.0 threshold.)

## Wins
- **Throughput unstuck: 58 carousels generated (was 2).**
- 21 generated in a single triggered run with even hook-style distribution (3 of each style).
- Top variant: `hot_take + real_life_inspiration` (avg 60.0).

## Fixes this run
- **Image discovery no longer blocks the generation loop.** [scheduler_service.py:_run_character_content_generation](../../backend/app/services/scheduler_service.py) now caps per-run discoveries at 5 and fires them as `asyncio.create_task` (fire-and-forget) via new `_safe_image_discovery` helper. Also added a `max_visits` (4× max_per_run) cap so one stuck subsystem can't burn the whole hourly budget.
- **LLM fallback chain now defaults to Kimi when no task_type provided.** [llm_router.py:resolve_provider_model](../../backend/app/infrastructure/llm_router.py) had a bug: when callers passed `model="vllm/qwen3-chat"` without a `task_type`, `assignment` was None and `fallbacks=[]`. So when vllm's circuit broke, generation died with "All LLM providers failed" without ever trying Kimi. Added `_DEFAULT_FALLBACKS = ["kimi/kimi-k2-0905-preview", "vllm/qwen3-chat"]` used when no assignment-specific chain exists.
- **OOM at 2GB memory limit.** Carousel generation flooded the box once Kimi fallbacks started flowing. Bumped `zero-api` memory in [docker-compose.sprint.yml](../../docker-compose.sprint.yml) from 2G → 4G. Steady-state usage is ~3.4G under load.

## Last check-in: 2026-04-21 (post-fix)
