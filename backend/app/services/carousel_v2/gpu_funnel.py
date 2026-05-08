"""GPU-bound stages of the 11-stage image funnel — CLIP relevance, LAION
aesthetic v2, InsightFace face verify, Florence-2 watermark detection.

Imported lazily by ``image_scorer_service`` only when
``ZERO_USE_LOCAL_VISION_FUNNEL=true``. Each stage is best-effort; missing
weights / GPU / packages are logged and skipped, leaving the cheap-CV +
cloud-VLM path operational.

This module exists as a clean integration seam: when GPU passthrough lands
in ``zero-api``, drop in real implementations (``open_clip`` / ``pyiqa`` /
``insightface`` / ``florence``) without touching the workflow or scorer.
"""

from __future__ import annotations

from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


async def run_clip_aesthetic_face_watermark(
    survivors,
    *,
    character: str,
    franchise: Optional[str] = None,
) -> None:
    """Stages 3-6 of the 11-stage funnel.

    Annotates each ``ScoredCandidate`` in place with ``clip_relevance``,
    ``aesthetic_v2``, ``maniqa``, ``face_cosine``, ``face_actor``,
    ``watermark_flag``, ``text_overlay_flag``.

    Phase 2 default: no-op stub. Phase 5 (or whenever GPU lands) wires the
    real models. The composite z still ranks usefully without these signals
    because the cheap-CV + VLM signals dominate the weight when GPU signals
    are zero.
    """
    logger.info(
        "gpu_funnel_stub",
        survivors=len(survivors),
        character=character,
        franchise=franchise,
    )
    # Real wiring goes here. See carosel.txt §1 stages 3-6 for model choices.
    return None
