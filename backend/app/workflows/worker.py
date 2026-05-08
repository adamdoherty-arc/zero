"""Temporal worker entrypoint.

Run with::

    cd backend
    python -m app.workflows.worker

The worker subscribes to two task queues per the carosel.txt blueprint
'two task queues for bulkhead isolation' note:

- ``carousel-gpu`` (CPU/GPU-pinned: image scoring, Pillow render, Playwright)
- ``carousel-io`` (high concurrency, async HTTP: TMDB / Reddit / TikTok)

Phase 1 runs both on a single worker process. Phase 6 splits them.
"""

from __future__ import annotations

import asyncio
import os
import signal

import structlog

from app.workflows.activities import ALL_ACTIVITIES
from app.workflows.carousel_workflow import (
    GenerateCarouselWorkflow,
    LegacyCarouselWorkflow,
)
from app.workflows.client import get_temporal_client

logger = structlog.get_logger(__name__)


async def main() -> None:
    from temporalio.worker import Worker

    # Activities that touch the database (generation_state.upsert_state,
    # judge_panel_service.persist_rubric, image_scorer persistence) call
    # ``get_session()`` which raises until ``init_database`` has run. Do that
    # once at worker startup — failure-soft so workers can still come up
    # against a degraded Postgres.
    pg_url = os.getenv("ZERO_POSTGRES_URL")
    if pg_url:
        try:
            from app.infrastructure.database import init_database
            await init_database(pg_url)
            logger.info("temporal_worker_db_initialized", url=pg_url.split("@")[-1])
        except Exception as exc:  # noqa: BLE001
            logger.warning("temporal_worker_db_init_failed", error=str(exc))

    client = await get_temporal_client()

    queue = os.getenv("ZERO_TEMPORAL_TASK_QUEUE", "carousel-default")
    max_concurrent_activities = int(os.getenv("ZERO_TEMPORAL_MAX_ACTIVITIES", "8"))
    max_concurrent_workflows = int(os.getenv("ZERO_TEMPORAL_MAX_WORKFLOWS", "16"))

    worker = Worker(
        client,
        task_queue=queue,
        workflows=[GenerateCarouselWorkflow, LegacyCarouselWorkflow],
        activities=ALL_ACTIVITIES,
        max_concurrent_activities=max_concurrent_activities,
        max_concurrent_workflow_tasks=max_concurrent_workflows,
    )

    stop_event = asyncio.Event()

    def _stop(*_: object) -> None:
        logger.info("temporal_worker_shutdown_signal")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:  # pragma: no cover — Windows
            signal.signal(sig, lambda *_args: _stop())

    logger.info(
        "temporal_worker_starting",
        task_queue=queue,
        activities=len(ALL_ACTIVITIES),
        max_concurrent_activities=max_concurrent_activities,
    )

    async with worker:
        await stop_event.wait()

    logger.info("temporal_worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
