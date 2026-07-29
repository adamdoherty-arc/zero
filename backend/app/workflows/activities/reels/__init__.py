"""Temporal activities for the motivation-reel workflow.

Thin wrappers over ``app.services.reels`` stage logic so the durable pipeline
and the direct orchestrator share one implementation. Registered into the
worker via ``REEL_ACTIVITIES``.
"""

from app.workflows.activities.reels import generate, publish, review

REEL_ACTIVITIES = [
    generate.run_reel_generation,
    review.request_reel_review,
    publish.publish_reel_activity,
]
