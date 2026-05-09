"""End-to-end smoke test for the carousel V2 pipeline.

Connects to:
  - Temporal at zero-temporal:7233 (in-network)
  - Postgres at zero-postgres:5432 (in-network)

Stubs:
  - Image curator + scorer (no real TMDB / Reddit calls)
  - LLM router (canned designer / skeptic / judge JSON)
  - Research (skip the Fandom / IMDb HTTP fetch)

Run inside a container with the new V2 deps installed. From the host:

    docker run --rm \\
      --network zero-network \\
      -v c:/code/zero/backend:/app \\
      -w /app \\
      -e ZERO_POSTGRES_URL=postgresql+psycopg://zero:zero_secret@zero-postgres:5432/zero \\
      -e ZERO_TEMPORAL_HOST=zero-temporal:7233 \\
      python:3.11-slim \\
      bash -c "pip install -q --no-cache-dir 'temporalio>=1.10.0' 'sqlalchemy[asyncio]' 'psycopg[binary]' 'pgvector' 'structlog' 'pydantic>=2.10' 'pydantic-settings' 'PyYAML' 'httpx' 'instructor' 'pillow' 'imagehash' 'opencv-python-headless' 'jinja2' 'asyncpg' 'aioboto3' 'aiometer' && python smoke_test_carousel_v2.py"
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, ".")


# ---------------------------------------------------------------------------
# Stubs — applied before any module-level imports that depend on them.
# ---------------------------------------------------------------------------

from app.services.image_curator_service import ImageCuratorService
from app.services.image_sources.types import CandidateImage


async def _curate_stub(self, query, **kw):
    return [
        CandidateImage(source="tmdb", source_url="https://i/tmdb1.jpg", width=1920, height=1080),
        CandidateImage(source="fanart", source_url="https://i/fanart1.png", width=2048, height=1152),
    ]


ImageCuratorService.curate = _curate_stub

from app.models.carousel import ImageScore, ImageSourceKind
import app.services.image_scorer_service as scorer_mod


class _ScorerStub:
    async def score(self, candidates, *, character, franchise=None, **kw):
        return [
            ImageScore(
                id="abc",
                source=ImageSourceKind.TMDB,
                source_url="https://i/tmdb1.jpg",
                composite_z=1.5,
                rank=0,
                kept=True,
            )
        ]


scorer_mod.get_image_scorer = lambda: _ScorerStub()


class _LLMStub:
    async def structured_chat(self, prompt, **kw):
        task = kw.get("task_type", "")
        if task == "hook_writer":
            return {"hook": "Homelander wasn't supposed to be the villain"}
        if task == "hook_judge":
            return {"index": 1}
        if task == "designer":
            return [
                {
                    "slide_num": 1,
                    "role": "hook",
                    "text": "Homelander wasn't supposed to be the villain",
                    "transition_to_next": "but here's why...",
                    "cited_fact_ids": [],
                },
                {
                    "slide_num": 2,
                    "role": "build",
                    "text": "Vought engineered him from infancy [fact_id:abc123]",
                    "transition_to_next": "and that's just the start",
                    "cited_fact_ids": ["abc123"],
                },
            ]
        if task == "skeptic":
            return [
                {
                    "claim": "Vought engineered him from infancy [fact_id:abc123]",
                    "verdict": "KEEP",
                    "trap_category": None,
                    "supporting_quote": None,
                    "rewrite_suggestion": None,
                }
            ]
        if task.startswith("judge_"):
            return {"score": 8.0, "rationale": "anchored well, hook stops scroll"}
        return {}

    async def chat(self, *a, **kw):
        return ""


import app.infrastructure.unified_llm_client as ullm_mod

ullm_mod.UnifiedLLMClient = lambda: _LLMStub()


# Research activity needs no stub — its failure-soft branch fires when
# ``gather_research_fragments`` isn't importable (the legacy module exposes
# ``get_research_sources()`` instead, so the import inside the activity raises
# and the activity returns an empty atomic_facts list).


# ---------------------------------------------------------------------------
# Workflow run
# ---------------------------------------------------------------------------

from app.infrastructure.database import init_database
from app.models.carousel import CarouselWorkflowInput
from app.workflows.activities import ALL_ACTIVITIES
from app.workflows.carousel_workflow import GenerateCarouselWorkflow, LegacyCarouselWorkflow


async def main() -> str:
    pg_url = os.environ["ZERO_POSTGRES_URL"]
    tm_host = os.environ.get("ZERO_TEMPORAL_HOST", "zero-temporal:7233")

    await init_database(pg_url)
    print(f"DB initialized → {pg_url.split('@')[-1]}")

    from temporalio.client import Client
    from temporalio.contrib.pydantic import pydantic_data_converter
    from temporalio.worker import Worker

    client = await Client.connect(
        tm_host, namespace="default", data_converter=pydantic_data_converter
    )
    print(f"Connected to Temporal at {tm_host}")

    worker = Worker(
        client,
        task_queue="carousel-default",
        workflows=[GenerateCarouselWorkflow, LegacyCarouselWorkflow],
        activities=ALL_ACTIVITIES,
        max_concurrent_activities=4,
        max_concurrent_workflow_tasks=4,
    )

    async def run_workflow() -> str:
        await asyncio.sleep(1.0)
        payload = CarouselWorkflowInput(
            topic="Homelander",
            franchise="the_boys",
            slide_count=5,
            auto_publish=True,
            voice_file="the_boys",
        )
        handle = await client.start_workflow(
            GenerateCarouselWorkflow.run,
            payload,
            id=f"carousel-smoke-{os.getpid()}",
            task_queue="carousel-default",
        )
        print(f"Started workflow: {handle.id}")
        result = await asyncio.wait_for(handle.result(), timeout=120.0)
        print(f"Workflow result:")
        print(f"  generation_id: {result.generation_id}")
        print(f"  status:        {result.status}")
        print(f"  composite:     {result.composite_score}")
        print(f"  publish_id:    {result.publish_id}")
        return result.generation_id

    worker_task = asyncio.create_task(worker.run())
    try:
        gen_id = await run_workflow()
    finally:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
    return gen_id


async def verify(gen_id: str) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text

    engine = create_async_engine(os.environ["ZERO_POSTGRES_URL"])
    async with engine.connect() as conn:
        cg = (
            await conn.execute(
                text(
                    "SELECT id, topic, franchise, status, composite_score, revision_count "
                    "FROM carousel_generations WHERE id = :i"
                ),
                {"i": gen_id},
            )
        ).first()
        js = (
            await conn.execute(
                text("SELECT count(*) FROM judge_scores WHERE generation_id = :i"),
                {"i": gen_id},
            )
        ).scalar()
        eg = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM engagement_signals WHERE generation_id = :i"
                ),
                {"i": gen_id},
            )
        ).scalar()
        idem = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM idempotency_keys WHERE generation_id = :i"
                ),
                {"i": gen_id},
            )
        ).scalar()
    await engine.dispose()

    print()
    print("=" * 60)
    print("End-to-end persistence check")
    print("=" * 60)
    if cg is None:
        print(f"carousel_generations row: MISSING for {gen_id}")
    else:
        print(f"carousel_generations: id={cg.id}")
        print(f"  topic={cg.topic} franchise={cg.franchise}")
        print(f"  status={cg.status} composite={cg.composite_score} revisions={cg.revision_count}")
    print(f"judge_scores rows:        {js}")
    print(f"engagement_signals rows:  {eg}")
    print(f"idempotency_keys rows:    {idem}")


if __name__ == "__main__":
    gen_id = asyncio.run(main())
    asyncio.run(verify(gen_id))
