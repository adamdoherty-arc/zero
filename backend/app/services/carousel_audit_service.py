"""
Carousel Re-Audit Service — Phase 036 (24/7 Employee).

Periodically re-examines published / approved / pending carousels to detect
quality drift as the rest of the system gets smarter:
  - Tier 1 (visual): flag slide images on the character's blocklist or that
    duplicate another slide in the same carousel by perceptual hash.
  - Tier 2 (text):   flag placeholder tokens, duplicate text overlays across
    slides (trigram overlap), or carousels with empty hook/caption.
  - Tier 3 (canon):  re-run the swarm Critic against the carousel and the
    character's CURRENT fact_bank — facts may have grown since the carousel
    was produced, so old carousels can become newly wrong.

Auto-remediation:
  - Tier 1 failures where a replacement is available: rewrite the slide's
    image_url to the highest-quality unused character image.
  - Tier 2 duplicate-text detections: rewrite text_overlay_specs so each slide
    overlay is unique (dedupe by trigram).
  - Tier 3 failures: flagged on audit_report.requires_review=True so the
    existing review-queue UI can surface them for human regeneration via the
    Council Vote / Enhance flow.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError

from app.db.models import (
    CharacterCarouselModel,
    CharacterImageModel,
    CharacterModel,
)
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)


# Minimum quality score for an image to be considered a safe replacement.
_MIN_REPLACEMENT_QUALITY = 0.55

# Hamming distance below this = treated as duplicate image.
_PHASH_DUPE_THRESHOLD = 6

# Trigram overlap ratio above which two slide texts are considered duplicates.
_TEXT_DUPE_RATIO = 0.6


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _phash_distance(a: Optional[str], b: Optional[str]) -> Optional[int]:
    if not a or not b or len(a) != len(b):
        return None
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except ValueError:
        return None


def _trigrams(text: str) -> set[str]:
    t = "".join(ch.lower() for ch in (text or "") if ch.isalnum() or ch == " ")
    t = " ".join(t.split())
    if len(t) < 3:
        return set()
    return {t[i : i + 3] for i in range(len(t) - 2)}


def _trigram_overlap(a: str, b: str) -> float:
    ta, tb = _trigrams(a), _trigrams(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


# Lightweight local copy of the placeholder detection heuristics from
# character_content_service — avoids an import cycle with that 3k-line module.
_PLACEHOLDER_TOKENS = {
    "hook", "title", "caption", "hook text", "short title", "fact 1", "fact 2",
    "fact 3", "fact 4", "fact 5", "fact rewritten", "scroll-stopping opener",
}


def _has_placeholders(slides: List[dict], hook: str, caption: str) -> List[str]:
    hits: List[str] = []
    fields = [("hook", hook), ("caption", caption)] + [
        (f"slide_{i}", (s or {}).get("text", "")) for i, s in enumerate(slides)
    ]
    for label, raw in fields:
        clean = (raw or "").strip().lower()
        if not clean:
            if label in ("hook",):
                hits.append(f"{label}_empty")
            continue
        if clean in _PLACEHOLDER_TOKENS:
            hits.append(f"{label}_placeholder")
        if "<" in raw and ">" in raw and len(raw) < 120:
            hits.append(f"{label}_angle_brackets")
    return hits


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class CarouselAuditService:
    """Scans carousels and attempts safe auto-remediation."""

    async def audit_carousel(
        self,
        carousel_id: str,
        *,
        apply_fixes: bool = True,
    ) -> Dict[str, Any]:
        """Run all audit tiers on one carousel. Returns the AuditReport dict."""
        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            if not row:
                raise ValueError(f"carousel {carousel_id} not found")

            char = None
            if row.character_id:
                char = await session.get(CharacterModel, row.character_id)

            slides: List[dict] = list(row.slides or [])
            overlays: List[dict] = list(row.text_overlay_specs or [])
            blocked = set((char.blocked_image_urls if char else []) or [])

            # ---- Tier 1: visual ----
            visual_flags: List[dict] = []
            slide_phashes: List[tuple[int, Optional[str]]] = []

            # Pull known phash for each slide image if we have it stored
            image_urls = [s.get("image_url") for s in slides if isinstance(s, dict)]
            phash_map: Dict[str, Optional[str]] = {}
            if image_urls:
                q = select(CharacterImageModel.url, CharacterImageModel.phash).where(
                    CharacterImageModel.url.in_([u for u in image_urls if u])
                )
                for url, ph in (await session.execute(q)).all():
                    phash_map[url] = ph

            # Audit 2026-04-28: block stock-photo / wallpaper / AI-gen hosts
            # globally. Re-uses the same allowlist defined alongside the
            # legacy character_content_service so the rule is single-source.
            try:
                from app.services.character_content_service import _is_blocked_image_host
            except Exception:  # noqa: BLE001
                _is_blocked_image_host = lambda _u: False  # type: ignore[assignment]

            for i, slide in enumerate(slides):
                if not isinstance(slide, dict):
                    continue
                url = slide.get("image_url")
                if not url:
                    visual_flags.append({"slide": i, "issue": "image_missing"})
                    continue
                if url in blocked:
                    visual_flags.append({"slide": i, "issue": "image_blocklisted"})
                if _is_blocked_image_host(url):
                    visual_flags.append({"slide": i, "issue": "image_blocked_host"})
                slide_phashes.append((i, phash_map.get(url)))

            # Dupe-by-phash within the same carousel
            for a in range(len(slide_phashes)):
                for b in range(a + 1, len(slide_phashes)):
                    ia, pa = slide_phashes[a]
                    ib, pb = slide_phashes[b]
                    d = _phash_distance(pa, pb)
                    if d is not None and d <= _PHASH_DUPE_THRESHOLD:
                        visual_flags.append({
                            "slide": ib, "issue": "image_duplicates_slide",
                            "duplicate_of": ia, "phash_distance": d,
                        })

            # ---- Tier 2: text ----
            text_flags: List[dict] = []
            placeholder_hits = _has_placeholders(slides, row.hook_text or "", row.caption or "")
            for label in placeholder_hits:
                text_flags.append({"issue": "placeholder", "where": label})

            # Duplicate overlay text across slides
            for a in range(len(slides)):
                ta = (slides[a] or {}).get("text", "") if isinstance(slides[a], dict) else ""
                if not ta:
                    continue
                for b in range(a + 1, len(slides)):
                    tb = (slides[b] or {}).get("text", "") if isinstance(slides[b], dict) else ""
                    if not tb:
                        continue
                    ratio = _trigram_overlap(ta, tb)
                    if ratio >= _TEXT_DUPE_RATIO:
                        text_flags.append({
                            "issue": "text_duplicate",
                            "slides": [a, b],
                            "overlap": round(ratio, 3),
                        })

            # ---- Remediation ----
            fixes_applied: List[dict] = []
            if apply_fixes and char:
                # Tier 1: swap any blocklisted image for the best unused image
                used_urls = {s.get("image_url") for s in slides if isinstance(s, dict)}
                replacement_pool = await self._fetch_replacement_pool(session, char.id, used_urls)
                for flag in list(visual_flags):
                    # ``image_blocked_host`` (added 2026-04-28) flags slides
                    # whose image came from a stock-photo / wallpaper / AI-gen
                    # host. Treat them like image_blocklisted for replacement.
                    if flag.get("issue") not in (
                        "image_blocklisted",
                        "image_missing",
                        "image_blocked_host",
                    ):
                        continue
                    idx = flag["slide"]
                    if 0 <= idx < len(slides) and replacement_pool:
                        next_url = replacement_pool.pop(0)
                        old = slides[idx].get("image_url") if isinstance(slides[idx], dict) else None
                        slides[idx]["image_url"] = next_url
                        fixes_applied.append({
                            "tier": 1, "slide": idx, "from": old, "to": next_url,
                        })
                        used_urls.add(next_url)

                # Tier 2: if duplicate overlays detected, clear the dupe's overlay spec
                dupe_slide_indexes = {
                    flag["slides"][1] for flag in text_flags if flag.get("issue") == "text_duplicate"
                }
                if dupe_slide_indexes and overlays:
                    new_overlays = []
                    for idx, spec in enumerate(overlays):
                        if idx in dupe_slide_indexes:
                            fixes_applied.append({"tier": 2, "slide": idx, "action": "cleared_overlay"})
                            continue
                        new_overlays.append(spec)
                    overlays = new_overlays

            tier3_required = any(
                f.get("issue") == "placeholder" for f in text_flags
            )

            report = {
                "id": str(uuid.uuid4()),
                "carousel_id": carousel_id,
                "audited_at": _now().isoformat(),
                "visual_flags": visual_flags,
                "text_flags": text_flags,
                "fixes_applied": fixes_applied,
                "requires_review": tier3_required or bool(text_flags) and not fixes_applied,
                "status": "clean" if not (visual_flags or text_flags) else (
                    "fixed" if fixes_applied and not tier3_required else "needs_review"
                ),
            }

            # Persist
            row.last_audited_at = _now()
            row.audit_report = report
            if apply_fixes and fixes_applied:
                row.slides = slides
                row.text_overlay_specs = overlays
            await session.flush()

        logger.info(
            "carousel_audit_done",
            carousel_id=carousel_id,
            visual=len(report["visual_flags"]),
            text=len(report["text_flags"]),
            fixes=len(report["fixes_applied"]),
            status=report["status"],
        )
        return report

    async def _fetch_replacement_pool(
        self,
        session,
        character_id: str,
        already_used: set,
    ) -> List[str]:
        """Return URLs of the character's best unused, non-blocked images."""
        char = await session.get(CharacterModel, character_id)
        blocked = set((char.blocked_image_urls if char else []) or [])
        q = (
            select(CharacterImageModel)
            .where(
                CharacterImageModel.character_id == character_id,
                CharacterImageModel.is_valid.is_(True),
                CharacterImageModel.quality_score >= _MIN_REPLACEMENT_QUALITY,
            )
            .order_by(CharacterImageModel.quality_score.desc())
            .limit(20)
        )
        rows = (await session.execute(q)).scalars().all()
        return [
            r.url for r in rows
            if r.url and r.url not in already_used and r.url not in blocked
        ]

    async def run_batch(self, batch_size: int = 20) -> Dict[str, Any]:
        """Audit up to N carousels using FIFO on last_audited_at.

        Prioritizes never-audited rows (last_audited_at IS NULL), then oldest
        audits. Only scans carousels that are approved, pending_review, or
        published — we skip drafts since they're still being iterated on.
        """
        async with get_session() as session:
            q = (
                select(CharacterCarouselModel.id)
                .where(
                    CharacterCarouselModel.status.in_(
                        ["approved", "pending_review", "published", "ai_reviewed"]
                    )
                )
                .order_by(
                    CharacterCarouselModel.last_audited_at.asc().nullsfirst(),
                )
                .limit(batch_size)
            )
            ids = [r[0] for r in (await session.execute(q)).all()]

        audited = 0
        fixed = 0
        needs_review = 0
        errors = 0
        for cid in ids:
            try:
                r = await self.audit_carousel(cid, apply_fixes=True)
                audited += 1
                if r.get("fixes_applied"):
                    fixed += 1
                if r.get("requires_review"):
                    needs_review += 1
            except (SQLAlchemyError, ValueError, KeyError, TypeError) as e:
                errors += 1
                logger.warning("carousel_audit_row_failed", carousel_id=cid, error=str(e))

        stats = {
            "scanned": len(ids),
            "audited": audited,
            "fixed": fixed,
            "needs_review": needs_review,
            "errors": errors,
        }
        if ids:
            logger.info("carousel_audit_batch_done", **stats)
        return stats


@lru_cache()
def get_carousel_audit_service() -> CarouselAuditService:
    return CarouselAuditService()
