"""Temporal activities for ZERO carousel workflows.

Each activity carries the actual I/O for a workflow stage. Activities are
discovered by the worker via the ``ALL_ACTIVITIES`` list at the bottom of
this module.

Phase 1: most activities are stubs that pass state forward and write a row to
``carousel_generations``. They become real implementations across Phases 2-5
without changing the workflow signature.
"""

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
    topic,
)

ALL_ACTIVITIES = [
    topic.select_topic,
    research.research,
    curate_images.curate_images,
    score_images.score_images,
    design.design_carousel,
    skeptic.skeptic_review,
    reflexion.judge_and_reflect,
    render.render_slides,
    publish.request_human_review,
    publish.publish_to_tiktok,
    analytics.schedule_polls,
    legacy.legacy_generate,
]
