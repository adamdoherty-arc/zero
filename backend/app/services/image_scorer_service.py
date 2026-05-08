"""11-stage cascading image filter funnel (carosel.txt §1).

Stages in cost-ascending order — prune cheap first so the expensive VLM
verifier only sees the top ~30 candidates per character::

  1. Cheap CV       — resolution, blur (Laplacian variance), aspect, NSFW
  2. pHash + dHash  — BK-tree near-dupe collapse
  3. CLIP relevance — open_clip ViT-L-14 softmax over property prompts   [GPU]
  4. Aesthetic+IQA  — LAION aesthetic v2 + pyiqa MANIQA / CLIP-IQA+      [GPU]
  5. Face verify    — InsightFace buffalo_l vs reference embedding bank  [GPU]
  6. Watermark det. — Florence-2 OPEN_VOCABULARY_DETECTION               [GPU]
  7. Semantic dedup — CLIP-embedding cosine ≥0.94 collapse
  8. VLM verifier   — Gemini Flash via vision_service (cloud)            [CLOUD]
  9. Composite z    — weighted sum of all signals; rank
 10. Upscale        — Real-ESRGAN x4plus / GFPGAN                        [GPU/CLOUD]
 11. Smart crop     — mediapipe face-aware 9:16 with rule-of-thirds bias

GPU stages are gated behind ``ZERO_USE_LOCAL_VISION_FUNNEL`` and skipped when
no GPU is wired. They become no-ops that pass scores through. The composite
z still ranks usefully on the cloud-only signals (cheap CV + phash + VLM).
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import math
import os
from dataclasses import dataclass, field
from typing import Optional

import structlog

from app.models.carousel import ImageScore, ImageSourceKind
from app.services.image_sources.types import CandidateImage

logger = structlog.get_logger(__name__)


def _local_funnel_enabled() -> bool:
    return os.getenv("ZERO_USE_LOCAL_VISION_FUNNEL", "false").strip().lower() in {"1", "true", "yes"}


@dataclass
class ScoredCandidate:
    """Internal working object — hydrates ImageScore at the end."""
    cand: CandidateImage
    sha256: str
    width: int = 0
    height: int = 0
    blur_variance: Optional[float] = None
    aspect_match: bool = True
    phash: Optional[str] = None
    dhash: Optional[str] = None
    clip_relevance: Optional[float] = None
    clip_alt_softmax: dict[str, float] = field(default_factory=dict)
    aesthetic_v2: Optional[float] = None
    maniqa: Optional[float] = None
    face_cosine: Optional[float] = None
    face_actor: Optional[str] = None
    watermark_flag: bool = False
    text_overlay_flag: bool = False
    vlm_likeness: Optional[float] = None
    vlm_is_promotional_still: Optional[bool] = None
    vlm_response: dict = field(default_factory=dict)
    vlm_model: Optional[str] = None
    vlm_tier: Optional[str] = None
    vlm_cost_usd: Optional[float] = None
    composite_z: Optional[float] = None
    drop_reason: Optional[str] = None
    kept: bool = True


# ---------------------------------------------------------------------------
# Stage 1 — cheap CV
# ---------------------------------------------------------------------------

_MIN_DIM = 600          # tightened later once GPU paths are available
_MIN_BLUR_VAR = 60.0    # cv2.Laplacian variance
_OK_ASPECTS = ((4, 5), (9, 16), (1, 1), (16, 9), (3, 4))
_ASPECT_TOL = 0.10


def _aspect_ok(w: int, h: int) -> bool:
    if w <= 0 or h <= 0:
        return False
    a = w / h
    for nw, nh in _OK_ASPECTS:
        target = nw / nh
        if abs(a - target) / target <= _ASPECT_TOL:
            return True
    return False


async def _stage_cheap_cv(client, sc: ScoredCandidate) -> bool:
    """Download, run cheap CV. Returns False if the candidate must be dropped."""
    try:
        r = await client.get(sc.cand.source_url, timeout=15.0)
        r.raise_for_status()
        body = r.content
    except Exception as exc:  # noqa: BLE001
        sc.drop_reason = f"download_failed:{type(exc).__name__}"
        return False

    sc.sha256 = hashlib.sha256(body).hexdigest()

    try:
        from PIL import Image
        img = Image.open(io.BytesIO(body))
        img.load()
    except Exception as exc:  # noqa: BLE001
        sc.drop_reason = f"decode_failed:{type(exc).__name__}"
        return False

    sc.width, sc.height = img.size
    if min(sc.width, sc.height) < _MIN_DIM:
        sc.drop_reason = "too_small"
        return False
    sc.aspect_match = _aspect_ok(sc.width, sc.height)

    # Blur — optional, requires opencv-python-headless (already in requirements).
    try:
        import cv2
        import numpy as np

        gray = np.array(img.convert("L"))
        sc.blur_variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        if sc.blur_variance < _MIN_BLUR_VAR:
            sc.drop_reason = "too_blurry"
            return False
    except ImportError:
        pass  # Not fatal — accept without blur signal
    except Exception as exc:  # noqa: BLE001
        logger.debug("blur_check_failed", error=str(exc))

    # pHash / dHash — Stage 2 piggybacks on the same loaded image.
    try:
        import imagehash
        sc.phash = str(imagehash.phash(img))
        sc.dhash = str(imagehash.dhash(img))
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.debug("phash_failed", error=str(exc))

    return True


# ---------------------------------------------------------------------------
# Stage 2 — pHash dedup via Hamming distance
# ---------------------------------------------------------------------------

def _hamming(a: str, b: str) -> int:
    if not a or not b or len(a) != len(b):
        return 64
    return sum(c1 != c2 for c1, c2 in zip(a, b))


def _phash_dedup(scs: list[ScoredCandidate], threshold: int = 6) -> list[ScoredCandidate]:
    """Linear-scan dedup. Sufficient at our candidate volumes (≤500); a
    BK-tree is the right call if this ever bottlenecks.
    """
    kept: list[ScoredCandidate] = []
    for sc in scs:
        if not sc.phash:
            kept.append(sc)
            continue
        if any(s.phash and _hamming(s.phash, sc.phash) <= threshold for s in kept):
            sc.kept = False
            sc.drop_reason = "phash_duplicate"
            continue
        kept.append(sc)
    return kept


# ---------------------------------------------------------------------------
# Stage 8 — VLM final verifier (cheap_vlm_router: Gemini paid → free pool)
# ---------------------------------------------------------------------------

async def _stage_vlm_verify(
    sc: ScoredCandidate,
    *,
    character: str,
    franchise: Optional[str],
    generation_id: Optional[str] = None,
) -> None:
    """Stage-8 VLM verdict. Routes through the tiered cheap-VLM dispatcher
    (carosel.txt blueprint + 2026-04-28 routing plan):

      Tier 0: Gemini 3.1 Flash            (paid, budget-gated)
      Tier 1: OpenRouter free vision pool (rotates models × keys)

    The daily + per-carousel budget caps live in
    ``carousel_v2.vlm_budget``. ``generation_id`` is passed so the
    per-carousel cap can attribute spend back to the right row.

    Failure-soft. When every tier is exhausted/gated we leave
    ``vlm_likeness=None`` and let Stage 9 rank on cheap-CV signals only.
    """
    try:
        from app.services.carousel_v2.cheap_vlm_router import verify_image
    except ImportError:
        sc.vlm_response = {"skipped": "cheap_vlm_router_unavailable"}
        return

    try:
        resp = await verify_image(
            sc.cand.source_url,
            character=character,
            franchise=franchise,
            generation_id=generation_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("vlm_verify_failed", url=sc.cand.source_url, error=str(exc))
        sc.vlm_response = {"error": str(exc)[:200]}
        return

    sc.vlm_response = resp if isinstance(resp, dict) else {"raw": str(resp)[:500]}
    if isinstance(sc.vlm_response, dict):
        sc.vlm_model = sc.vlm_response.get("_model")
        sc.vlm_tier = sc.vlm_response.get("_tier")
        cost = sc.vlm_response.get("_cost_usd")
        if isinstance(cost, (int, float)):
            sc.vlm_cost_usd = float(cost)
        likeness = sc.vlm_response.get("likeness")
        if isinstance(likeness, (int, float)):
            sc.vlm_likeness = float(likeness)
        sc.vlm_is_promotional_still = bool(sc.vlm_response.get("is_promotional_still")) \
            if sc.vlm_response.get("is_promotional_still") is not None else None
        if sc.vlm_response.get("watermark"):
            sc.watermark_flag = True
        if sc.vlm_response.get("text_overlay"):
            sc.text_overlay_flag = True


# ---------------------------------------------------------------------------
# Stage 9 — composite z-score
# ---------------------------------------------------------------------------

def _z(values: list[float]) -> list[float]:
    if not values:
        return []
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / max(len(values), 1)
    sd = math.sqrt(var) or 1.0
    return [(v - mean) / sd for v in values]


def _composite(scs: list[ScoredCandidate]) -> None:
    """Weights from carosel.txt §1 stage 9. Penalties applied last."""
    aesthetic = [sc.aesthetic_v2 or 0.0 for sc in scs]
    clip = [sc.clip_relevance or 0.0 for sc in scs]
    face = [sc.face_cosine or 0.0 for sc in scs]
    maniqa = [sc.maniqa or 0.0 for sc in scs]
    res = [math.log(max(sc.width, 1) * max(sc.height, 1) + 1) for sc in scs]
    vlm = [sc.vlm_likeness or 0.0 for sc in scs]

    z_a, z_c, z_f, z_m, z_r, z_v = (_z(x) for x in (aesthetic, clip, face, maniqa, res, vlm))

    for i, sc in enumerate(scs):
        score = (
            0.30 * z_a[i] + 0.25 * z_c[i] + 0.15 * z_f[i] + 0.10 * z_m[i]
            + 0.10 * z_r[i] + 0.05 * z_v[i]
            - 0.50 * float(sc.watermark_flag)
            - 0.30 * float(sc.text_overlay_flag)
            - 0.20 * (0.0 if sc.aspect_match else 1.0)
        )
        sc.composite_z = score


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class ImageScorerService:
    async def score(
        self,
        candidates: list[CandidateImage],
        *,
        character: str,
        franchise: Optional[str] = None,
        top_k: int = 30,
        vlm_top_k: int = 30,
        max_concurrent_downloads: int = 8,
        generation_id: Optional[str] = None,
    ) -> list[ImageScore]:
        if not candidates:
            return []

        scs = [ScoredCandidate(cand=c, sha256="") for c in candidates]
        sem = asyncio.Semaphore(max_concurrent_downloads)

        import httpx
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:

            async def _gate(sc: ScoredCandidate) -> None:
                async with sem:
                    if not await _stage_cheap_cv(client, sc):
                        sc.kept = False

            await asyncio.gather(*(_gate(sc) for sc in scs))

        # Stage 2 dedup over survivors
        survivors = [s for s in scs if s.kept]
        survivors = _phash_dedup(survivors)

        # Stages 3-7 (heavy GPU): run only when local funnel is enabled.
        if _local_funnel_enabled():
            try:
                from app.services.carousel_v2 import gpu_funnel  # local module, see below
                await gpu_funnel.run_clip_aesthetic_face_watermark(survivors, character=character, franchise=franchise)
            except Exception as exc:  # noqa: BLE001
                logger.warning("gpu_funnel_failed", error=str(exc))

        # Stage 8 — VLM final verify on top-K-by-rank-so-far. Until stages 3-7
        # are wired the rank is purely cheap-CV; we just take all survivors
        # capped at vlm_top_k.
        survivors_to_vlm = survivors[:vlm_top_k]
        await asyncio.gather(
            *(
                _stage_vlm_verify(
                    sc,
                    character=character,
                    franchise=franchise,
                    generation_id=generation_id,
                )
                for sc in survivors_to_vlm
            )
        )

        _composite(survivors)
        survivors.sort(key=lambda s: (s.composite_z or -1e9), reverse=True)

        kept = survivors[:top_k]
        for s in survivors[top_k:]:
            s.kept = False
            s.drop_reason = s.drop_reason or "below_top_k"

        scored: list[ImageScore] = []
        for rank, sc in enumerate(kept):
            scored.append(_to_image_score(sc, rank=rank, kept=True))
        for sc in scs:
            if sc not in kept:
                scored.append(_to_image_score(sc, rank=None, kept=False))
        return scored


def _to_image_score(sc: ScoredCandidate, *, rank: Optional[int], kept: bool) -> ImageScore:
    try:
        source_kind = ImageSourceKind(sc.cand.source)
    except ValueError:
        source_kind = ImageSourceKind.PEXELS  # safest generic
    return ImageScore(
        id=sc.sha256[:32] or hashlib.sha1(sc.cand.source_url.encode()).hexdigest()[:32],
        source=source_kind,
        source_url=sc.cand.source_url,
        phash=sc.phash,
        dhash=sc.dhash,
        width=sc.width or sc.cand.width,
        height=sc.height or sc.cand.height,
        blur_variance=sc.blur_variance,
        aspect_match=sc.aspect_match,
        clip_relevance=sc.clip_relevance,
        clip_alt_softmax=sc.clip_alt_softmax,
        aesthetic_v2=sc.aesthetic_v2,
        maniqa=sc.maniqa,
        face_cosine=sc.face_cosine,
        face_actor=sc.face_actor,
        watermark_flag=sc.watermark_flag,
        text_overlay_flag=sc.text_overlay_flag,
        vlm_likeness=sc.vlm_likeness,
        vlm_is_promotional_still=sc.vlm_is_promotional_still,
        vlm_response=sc.vlm_response,
        vlm_model=sc.vlm_model,
        vlm_tier=sc.vlm_tier,
        vlm_cost_usd=sc.vlm_cost_usd,
        composite_z=sc.composite_z,
        rank=rank,
        kept=kept,
        drop_reason=sc.drop_reason,
    )


_INSTANCE: ImageScorerService | None = None


def get_image_scorer() -> ImageScorerService:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ImageScorerService()
    return _INSTANCE
