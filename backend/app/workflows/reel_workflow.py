"""GenerateMotivationReelWorkflow — durable quote→MP4→publish pipeline.

Parallel to ``GenerateCarouselWorkflow`` but for quote-driven video. Reuses the
same determinism rules: the workflow is pure orchestration, all I/O lives in
activities, and the publish boundary is gated by a human-review signal unless
``auto_publish`` is set.

Phase 1 runs generation as a single durable activity (the orchestrator) and
gates publishing with the ``human_decision`` signal. Phases 2-4 decompose
generation into per-stage activities + add the judge/reflexion loop without
changing this signature.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from app.models.reel import ReelGenerationStatus, ReelWorkflowInput, ReelWorkflowResult
    from app.workflows.activities.reels import generate, publish, review


DEFAULT_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=120),
    maximum_attempts=3,
    non_retryable_error_types=["AuthError", "ContentPolicyError", "InvalidInputError"],
)

PUBLISH_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=300),
    maximum_attempts=6,
    non_retryable_error_types=["AuthError", "ContentPolicyError", "DuplicatePublishError"],
)


@workflow.defn(name="GenerateMotivationReelWorkflow")
class GenerateMotivationReelWorkflow:
    """One reel from quote to publish. Crash-safe, idempotent at publish."""

    def __init__(self) -> None:
        self._human_approved: bool | None = None

    @workflow.signal
    def human_decision(self, approved: bool) -> None:
        self._human_approved = approved

    @workflow.run
    async def run(self, payload: ReelWorkflowInput) -> ReelWorkflowResult:
        # Generation is CPU-heavy (Playwright render + ffmpeg assemble) — give
        # it a long start-to-close timeout.
        result = await workflow.execute_activity(
            generate.run_reel_generation,
            payload,
            start_to_close_timeout=timedelta(minutes=20),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=DEFAULT_RETRY,
        )

        if result.get("status") == ReelGenerationStatus.FAILED.value:
            return ReelWorkflowResult(**result)

        # Human-in-the-loop gate (skipped when auto_publish).
        if not payload.auto_publish:
            await workflow.execute_activity(
                review.request_reel_review,
                result,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=DEFAULT_RETRY,
            )
            await workflow.wait_condition(lambda: self._human_approved is not None)
            if not self._human_approved:
                return ReelWorkflowResult(
                    generation_id=result["generation_id"],
                    reel_id=result.get("reel_id"),
                    status=ReelGenerationStatus.ABANDONED,
                    video_url=result.get("video_url"),
                    error="rejected_by_human",
                )

        pub = await workflow.execute_activity(
            publish.publish_reel_activity,
            {"generation_id": result["generation_id"], "platforms": payload.platforms},
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=PUBLISH_RETRY,
        )

        return ReelWorkflowResult(
            generation_id=result["generation_id"],
            reel_id=result.get("reel_id"),
            status=ReelGenerationStatus.PUBLISHED,
            video_url=result.get("video_url"),
            duration_s=result.get("duration_s"),
            composite_score=result.get("composite_score"),
            platform_publishes=pub.get("platform_publishes", []),
        )
