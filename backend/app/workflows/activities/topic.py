"""TopicSelector activity — first node in GenerateCarouselWorkflow.

Phase 1: stub — accepts the ``CarouselWorkflowInput`` and returns a context
dict that downstream activities thread through. Phase 3 wires the real
pgvector novelty filter (cos < 0.85 vs last 30 posts in the same niche).
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from temporalio import activity

from app.models.carousel import CarouselGenerationStatus, CarouselWorkflowInput

logger = structlog.get_logger(__name__)


@activity.defn
async def select_topic(payload: CarouselWorkflowInput) -> dict[str, Any]:
    """Stamp a generation_id and seed the workflow context."""
    generation_id = uuid.uuid4().hex
    activity.heartbeat({"stage": "topic", "generation_id": generation_id})

    logger.info(
        "carousel_topic_selected",
        generation_id=generation_id,
        topic=payload.topic,
        franchise=payload.franchise,
        character_id=payload.character_id,
    )

    # Create the persistent ``carousel_generations`` row so every downstream
    # judge/image/bandit row has a parent to reference.
    from app.services.carousel_v2.generation_state import upsert_state
    await upsert_state(
        generation_id,
        topic=payload.topic,
        franchise=payload.franchise,
        character_id=payload.character_id,
        prompt_version_id=payload.prompt_version_id,
        status=CarouselGenerationStatus.RESEARCHING.value,
    )

    return {
        "generation_id": generation_id,
        "input": payload.model_dump(mode="json"),
        "topic": payload.topic,
        "franchise": payload.franchise,
        "character_id": payload.character_id,
        "voice_file": payload.voice_file,
        "prompt_version_id": payload.prompt_version_id,
        "auto_publish": payload.auto_publish,
        "status": CarouselGenerationStatus.RESEARCHING.value,
        "novelty_ok": True,  # Phase 3 wires the real filter
    }
