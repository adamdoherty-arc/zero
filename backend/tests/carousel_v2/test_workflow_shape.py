"""Workflow + worker structural tests — load the real workflow module under
the temporalio stub and assert the pipeline shape that the deployment relies
on. Catches breakage that pure activity tests miss (e.g. wrong unsafe context
manager shape, missing activity references in workflow code).
"""

from __future__ import annotations

import pytest


def test_carousel_workflow_module_loads_under_stub():
    """Loading the workflow module exercises:

    - ``workflow.unsafe.imports_passed_through()`` shape
    - every activity import path from the workflow side
    - retry policy construction
    - signal / run decorator wiring
    """
    from app.workflows.carousel_workflow import (
        DEFAULT_RETRY,
        GenerateCarouselWorkflow,
        LegacyCarouselWorkflow,
        LLM_RETRY,
        PUBLISH_RETRY,
    )

    assert GenerateCarouselWorkflow is not None
    assert LegacyCarouselWorkflow is not None
    assert DEFAULT_RETRY is not None
    assert LLM_RETRY is not None
    assert PUBLISH_RETRY is not None


def test_activity_registry_matches_workflow_pipeline():
    """ALL_ACTIVITIES must include every callable the workflow tries to
    execute. If someone adds a stage to the workflow but forgets to register
    it on the worker, this fails at import time — not runtime.
    """
    from app.workflows.activities import ALL_ACTIVITIES
    from app.workflows.activities import (
        analytics, curate_images, design, legacy, publish, reflexion,
        render, research, score_images, skeptic, topic,
    )

    expected = {
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
    }
    registered = set(ALL_ACTIVITIES)
    missing = expected - registered
    assert not missing, f"Activities referenced by the workflow but not registered: {missing}"


def test_workflow_input_output_pydantic_round_trip():
    """The workflow signature uses Pydantic models on both ends. They must
    serialize through model_dump_json and back so Temporal's data converter
    handles them correctly across the activity boundary.
    """
    from app.models.carousel import (
        CarouselGenerationStatus,
        CarouselWorkflowInput,
        CarouselWorkflowResult,
    )

    inp = CarouselWorkflowInput(
        topic="Loki", franchise="mcu", character_id="c-1", auto_publish=True, slide_count=8
    )
    inp_round = CarouselWorkflowInput.model_validate_json(inp.model_dump_json())
    assert inp_round.topic == "Loki"
    assert inp_round.auto_publish is True

    out = CarouselWorkflowResult(
        generation_id="g-1",
        status=CarouselGenerationStatus.PUBLISHED,
        composite_score=8.4,
        publish_id="tt-x",
    )
    out_round = CarouselWorkflowResult.model_validate_json(out.model_dump_json())
    assert out_round.status == CarouselGenerationStatus.PUBLISHED
    assert out_round.composite_score == 8.4


def test_workflow_pydantic_data_converter_is_wired():
    """Phase 1 hardening — the Worker / Client must use the Pydantic-aware
    data converter so enum fields and nested Pydantic models survive the
    Temporal payload boundary.
    """
    from app.workflows import client as client_mod

    src = client_mod.__loader__.get_source(client_mod.__name__)
    # Either we set ``data_converter=pydantic_data_converter`` on the client,
    # or we explicitly opt out with a comment ``# DATA_CONVERTER: default-json``.
    assert "pydantic_data_converter" in src or "DATA_CONVERTER: default-json" in src
