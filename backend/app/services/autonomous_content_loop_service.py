"""Autonomous 24/7 content loop (W2 of orchestration hardening).

Drives carousel generation off unprocessed rows in TrendingSignalModel. Runs
on APScheduler every 30 minutes when ZERO_AUTONOMOUS_CONTENT_ENABLED is set.

Flow per tick:
  1. Pull the top-N unprocessed trending signals ordered by signal_strength
     and recency. A signal is "processed" when `triggered_content_at` is set.
  2. For each signal, resolve one or more linked_character_ids. If none exist
     on the signal row, fall back to franchise-based character discovery.
  3. For each character, skip if a carousel shipped in the last 24h
     (the existing per-character dedup in CharacterContentService guards
     against duplicates; this is a cheaper pre-filter).
  4. Invoke CharacterContentService.generate_carousel with swarm review on.
  5. Mark the signal triggered; log outcome.

Design notes:
  - Uses a module-level asyncio.Semaphore to cap concurrent carousel generation
    to 4 (GPU/LLM contention guard).
  - Per-universe daily cap (48) enforced against character_carousels.created_at
    on the trailing 24h.
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import List, Optional

import structlog
from sqlalchemy import and_, func, select

from app.db.models import (
    CharacterCarouselModel,
    CharacterModel,
    TrendingSignalModel,
)
from app.infrastructure.database import get_session
from app.models.character_content import CarouselCreate, ContentAngle

logger = structlog.get_logger(__name__)


_GEN_SEMAPHORE = asyncio.Semaphore(4)
_UNIVERSE_DAILY_CAP = 48
_SIGNAL_BATCH_SIZE = 8
_RECENT_SKIP_HOURS = 24
_ANGLES_BY_SIGNAL_TYPE = {
    "release": [ContentAngle.ORIGIN_STORY, ContentAngle.CHARACTER_EVOLUTION, ContentAngle.STORYLINE_RECAP],
    "trending": [ContentAngle.HIDDEN_TRUTHS, ContentAngle.DARK_FACTS, ContentAngle.POWER_SECRETS],
    "viral": [ContentAngle.CONTROVERSIAL_TAKES, ContentAngle.FAN_THEORIES, ContentAngle.HIDDEN_TRUTHS],
}


class AutonomousContentLoopService:
    """Pulls trending signals and drives carousel generation."""

    async def run_once(self) -> dict:
        """Execute a single loop iteration. Safe to call on a schedule.

        Returns a structured summary for audit logging.
        """
        if not await _is_enabled():
            logger.info("autonomous_content_loop_disabled")
            return {"status": "disabled"}

        signals = await self._fetch_unprocessed_signals()
        if not signals:
            logger.info("autonomous_content_loop_no_signals")
            return {"status": "idle", "signals": 0}

        # Dispatch generations. Per-signal async + shared semaphore keeps GPU sane.
        tasks = [asyncio.create_task(self._process_signal(s)) for s in signals]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        generated = sum(1 for r in results if isinstance(r, dict) and r.get("generated"))
        skipped = sum(1 for r in results if isinstance(r, dict) and r.get("skipped"))
        failed = sum(1 for r in results if isinstance(r, Exception))
        logger.info(
            "autonomous_content_loop_complete",
            signals=len(signals),
            generated=generated,
            skipped=skipped,
            failed=failed,
        )
        return {
            "status": "ok",
            "signals": len(signals),
            "generated": generated,
            "skipped": skipped,
            "failed": failed,
        }

    # ------------------------------------------------------------------

    async def _fetch_unprocessed_signals(self) -> List[TrendingSignalModel]:
        now = datetime.now(timezone.utc)
        async with get_session() as session:
            stmt = (
                select(TrendingSignalModel)
                .where(TrendingSignalModel.triggered_content_at.is_(None))
                .where(
                    (TrendingSignalModel.expires_at.is_(None))
                    | (TrendingSignalModel.expires_at > now)
                )
                .order_by(
                    TrendingSignalModel.signal_strength.desc(),
                    TrendingSignalModel.discovered_at.desc(),
                )
                .limit(_SIGNAL_BATCH_SIZE)
            )
            res = await session.execute(stmt)
            return list(res.scalars().all())

    async def _process_signal(self, signal: TrendingSignalModel) -> dict:
        character_ids = list(signal.linked_character_ids or [])
        if not character_ids and signal.franchise:
            character_ids = await self._characters_for_franchise(signal.franchise, limit=2)

        if not character_ids:
            logger.info("autonomous_content_loop_no_characters", signal_id=signal.id, franchise=signal.franchise)
            await self._mark_processed(signal.id)
            return {"signal_id": signal.id, "skipped": True, "reason": "no_characters"}

        angles_pool = _ANGLES_BY_SIGNAL_TYPE.get(signal.signal_type, list(ContentAngle))
        generated_any = False
        for character_id in character_ids[:2]:
            if await self._recently_generated(character_id, hours=_RECENT_SKIP_HOURS):
                continue
            if signal.universe and await self._universe_at_cap(signal.universe):
                logger.info("autonomous_content_loop_universe_cap", universe=signal.universe)
                break
            angle = random.choice(angles_pool)
            created = await self._generate_for(character_id=character_id, angle=angle, signal=signal)
            generated_any = generated_any or created

        await self._mark_processed(signal.id)
        return {"signal_id": signal.id, "generated": generated_any, "skipped": not generated_any}

    async def _generate_for(
        self,
        *,
        character_id: str,
        angle: ContentAngle,
        signal: TrendingSignalModel,
    ) -> bool:
        """Drive a single carousel through the durable graph.

        Uses CarouselGraphService.run() so we get pre-gen swarm veto, post-gen
        critique, rubric gate + Hamming dedup, and the retry edge for free —
        plus checkpointed state so a crash mid-generation resumes cleanly.
        """
        # Lazy import to sidestep circular dependency at module load time.
        from app.services.carousel_graph import get_carousel_graph_service

        async with _GEN_SEMAPHORE:
            try:
                graph_svc = get_carousel_graph_service()
                request = CarouselCreate(
                    character_id=character_id,
                    angle=angle,
                    slide_count=6,
                    use_swarm=False,  # the graph owns swarm orchestration
                )
                final_state = await graph_svc.run(request)
                carousel_id = final_state.get("carousel_id")
                rubric_passed = bool(final_state.get("rubric_passed"))
                logger.info(
                    "autonomous_content_loop_graph_complete",
                    character_id=character_id,
                    angle=angle.value,
                    carousel_id=carousel_id,
                    signal_id=signal.id,
                    rubric_passed=rubric_passed,
                    retries=final_state.get("retries", 0),
                    status=final_state.get("status"),
                )
                return bool(carousel_id)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "autonomous_content_loop_generate_failed",
                    character_id=character_id,
                    angle=angle.value,
                    signal_id=signal.id,
                    error=str(e)[:200],
                )
                return False

    async def _recently_generated(self, character_id: str, *, hours: int) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        async with get_session() as session:
            res = await session.execute(
                select(CharacterCarouselModel.id)
                .where(
                    and_(
                        CharacterCarouselModel.character_id == character_id,
                        CharacterCarouselModel.created_at >= cutoff,
                    )
                )
                .limit(1)
            )
            return res.scalar_one_or_none() is not None

    async def _universe_at_cap(self, universe: str) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        async with get_session() as session:
            # Join against CharacterModel to map universe on the carousel side.
            stmt = (
                select(func.count(CharacterCarouselModel.id))
                .join(CharacterModel, CharacterModel.id == CharacterCarouselModel.character_id)
                .where(CharacterModel.universe == universe)
                .where(CharacterCarouselModel.created_at >= cutoff)
            )
            res = await session.execute(stmt)
            count = res.scalar_one() or 0
        return count >= _UNIVERSE_DAILY_CAP

    async def _characters_for_franchise(self, franchise: str, *, limit: int) -> List[str]:
        async with get_session() as session:
            res = await session.execute(
                select(CharacterModel.id)
                .where(CharacterModel.franchise == franchise)
                .where(CharacterModel.fact_bank.isnot(None))
                .order_by(CharacterModel.research_depth_score.desc().nullslast())
                .limit(limit)
            )
            return [row[0] for row in res.all()]

    async def _mark_processed(self, signal_id: str) -> None:
        async with get_session() as session:
            row = await session.get(TrendingSignalModel, signal_id)
            if row is not None:
                row.triggered_content_at = datetime.now(timezone.utc)
                await session.commit()


async def _is_enabled() -> bool:
    """Feature flag lookup. Defaults false to match CLAUDE.md's opt-in stance."""
    try:
        from app.infrastructure.config import get_settings
        settings = get_settings()
        return bool(getattr(settings, "autonomous_content_enabled", False))
    except Exception:  # noqa: BLE001
        return False


@lru_cache()
def get_autonomous_content_loop_service() -> AutonomousContentLoopService:
    return AutonomousContentLoopService()
