"""GenerateCarouselWorkflow — Temporal workflow that walks one carousel from
topic to publish.

Pipeline (carosel.txt blueprint §0 'End-to-end architecture'):

  ① TopicSelector       — Qwen3-30B-A3B + pgvector novelty filter
  ② Researcher          — MiniMax M2.7 long-ctx + hybrid RAG
  ③ FactVerifier        — atomic claims → NLI → cross-source rule
  ④ ImageCurator        — fan-out to 8 sources via aiometer
  ⑤ ImageScorer         — 11-stage funnel
  ⑥ Designer            — DSPy-compiled, voice file injected, ToT for hooks
  ⑦ Skeptic             — Kimi K2.6 (different family from drafter)
  ⑧ Reflexion loop      — composite < 7.5 AND revisions < 3 → reflect → re-design
  ⑨ Render              — Pillow + numpy LUT/vignette/grain → Playwright
  ⑩ HumanReview         — Temporal interrupt() (skip if score ≥ auto-approve)
  ⑪ Publisher           — TikTok /v2/post/publish/content/init/
  ⑫ AnalyticsLoop       — every 6h × 48h, daily × 14d, weekly × 60d

Determinism rules:

- The workflow function is **pure orchestration**. No ``random``, no
  ``time.time()``, no direct API calls. Everything I/O happens in activities.
- Imports of heavy modules go through ``workflow.unsafe.imports_passed_through()``.
- Replay-safety: every retry resumes at the last successful activity, never
  the workflow start (Temporal history records every activity completion).

For Phase 1 the workflow runs in **legacy mode** — a single activity wraps
``CharacterContentService.generate_carousel()`` so existing traffic can flip
through Temporal via ``ZERO_USE_TEMPORAL=true`` without code changes elsewhere.
Per-stage activities (research, curate_images, design, skeptic, render,
publish) are stubbed and become real implementations across Phases 2-5.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from app.models.carousel import (
        CarouselGenerationStatus,
        CarouselWorkflowInput,
        CarouselWorkflowResult,
    )
    from app.workflows.activities import (
        analytics,
        curate_images,
        design,
        legacy,
        publish,
        reflexion,
        render,
        research,
        score_images,
        skeptic,
        topic as topic_activity,
    )


# Default retry policy — jittered exponential backoff. Activities can override.
DEFAULT_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
    maximum_attempts=5,
    non_retryable_error_types=["AuthError", "ContentPolicyError", "InvalidInputError"],
)

# Slow activities (LLM calls, image scoring) — longer timeouts.
LLM_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=120),
    maximum_attempts=4,
    non_retryable_error_types=["AuthError", "ContentPolicyError"],
)

PUBLISH_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=300),
    maximum_attempts=6,
    non_retryable_error_types=["AuthError", "ContentPolicyError", "DuplicatePublishError"],
)


@workflow.defn(name="GenerateCarouselWorkflow")
class GenerateCarouselWorkflow:
    """Single-carousel pipeline. Crash-safe, idempotent at the publish boundary."""

    def __init__(self) -> None:
        self._human_approved: bool | None = None

    @workflow.signal
    def human_decision(self, approved: bool) -> None:
        """Slack/Discord approval webhook signals this when a human acts."""
        self._human_approved = approved

    @workflow.run
    async def run(self, payload: CarouselWorkflowInput) -> CarouselWorkflowResult:
        # Phase 1: route through the legacy monolith. All eleven downstream
        # activities are wired but stubbed — they no-op and pass state forward
        # so the workflow shape exists in Temporal history from day one.
        # Phases 2-5 replace each stub with the real implementation.

        ctx = await workflow.execute_activity(
            topic_activity.select_topic,
            payload,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=DEFAULT_RETRY,
        )

        ctx = await workflow.execute_activity(
            research.research,
            ctx,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=LLM_RETRY,
        )

        ctx = await workflow.execute_activity(
            curate_images.curate_images,
            ctx,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=DEFAULT_RETRY,
        )

        ctx = await workflow.execute_activity(
            score_images.score_images,
            ctx,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=LLM_RETRY,
        )

        # Reflexion loop — at most 3 revisions before HITL.
        for revision in range(3):
            ctx = await workflow.execute_activity(
                design.design_carousel,
                ctx,
                start_to_close_timeout=timedelta(minutes=8),
                retry_policy=LLM_RETRY,
            )
            ctx = await workflow.execute_activity(
                skeptic.skeptic_review,
                ctx,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=LLM_RETRY,
            )
            qa = await workflow.execute_activity(
                reflexion.judge_and_reflect,
                ctx,
                start_to_close_timeout=timedelta(minutes=8),
                retry_policy=LLM_RETRY,
            )
            ctx = qa["context"]
            if qa["passes"]:
                break

        ctx = await workflow.execute_activity(
            render.render_slides,
            ctx,
            start_to_close_timeout=timedelta(minutes=8),
            retry_policy=DEFAULT_RETRY,
        )

        # Human-in-the-loop gate when composite < auto-publish threshold.
        if not ctx.get("auto_approved"):
            await workflow.execute_activity(
                publish.request_human_review,
                ctx,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=DEFAULT_RETRY,
            )
            await workflow.wait_condition(lambda: self._human_approved is not None)
            if not self._human_approved:
                return CarouselWorkflowResult(
                    generation_id=ctx["generation_id"],
                    carousel_id=ctx.get("carousel_id"),
                    status=CarouselGenerationStatus.ABANDONED,
                    composite_score=ctx.get("composite_score"),
                    error="rejected_by_human",
                )

        publish_result = await workflow.execute_activity(
            publish.publish_to_tiktok,
            ctx,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=PUBLISH_RETRY,
        )

        # Schedule analytics polls. Each is a child workflow / cron stub
        # in Phase 6; here we kick off the first poll as an activity.
        await workflow.execute_activity(
            analytics.schedule_polls,
            publish_result,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=DEFAULT_RETRY,
        )

        return CarouselWorkflowResult(
            generation_id=ctx["generation_id"],
            carousel_id=publish_result.get("carousel_id"),
            status=CarouselGenerationStatus.PUBLISHED,
            composite_score=ctx.get("composite_score"),
            publish_id=publish_result.get("publish_id"),
        )


@workflow.defn(name="LegacyCarouselWorkflow")
class LegacyCarouselWorkflow:
    """Phase 1 bridge — wraps ``CharacterContentService.generate_carousel()``
    in a single activity so existing traffic can flip through Temporal via
    ``ZERO_USE_TEMPORAL=true`` without touching the legacy pipeline.

    Decommissioned in Phase 6 once every per-stage activity is real.
    """

    @workflow.run
    async def run(self, payload: CarouselWorkflowInput) -> CarouselWorkflowResult:
        return await workflow.execute_activity(
            legacy.legacy_generate,
            payload,
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=5),
                backoff_coefficient=2.0,
                maximum_interval=timedelta(seconds=120),
                maximum_attempts=3,
                non_retryable_error_types=["AuthError", "ContentPolicyError"],
            ),
        )
