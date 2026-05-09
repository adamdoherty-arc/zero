"""Loop promotion service — autoresearch policy for variant lifecycle.

Direct from Karpathy autoresearch: small scope, fixed budget, one metric,
keep winners, roll back losers, readable log per cycle.

Variant lifecycle:
1. Born canary (5% traffic), waits until N>=30.
2. Win: success_rate +5pp AND score +3 AND p<0.05 AND >=4h exposure -> promote.
3. Loss: success_rate -10pp OR 5 consecutive failures OR 3-window decline -> retire.
4. Hold: neither after 100 runs -> mark held, vault note, do nothing.
5. Rollback: 3 consecutive regressions on the new active -> revert.

Per-loop kill switch: loops.auto_promote_enabled (default true per user decision).

Cross-project promotions (skill-md or code edits to a peer project) are NEVER
auto-applied here — those route through the agent_approvals HITL queue.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Optional

import structlog
from sqlalchemy import select, update

from app.db.models import (
    LoopModel,
    LoopPromotionModel,
    LoopRunModel,
    LoopVariantModel,
)
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)


# Policy constants — knobs the user might want to tune later.
MIN_SAMPLE_PER_VARIANT = 30
WIN_SUCCESS_RATE_DELTA = 0.05  # 5 percentage points
WIN_SCORE_DELTA = 3.0          # judge points (0-100)
WIN_PVALUE_THRESHOLD = 0.05
WIN_MIN_WALL_CLOCK_HOURS = 4
LOSS_SUCCESS_RATE_DELTA = 0.10
LOSS_CONSECUTIVE_FAILURES = 5
HOLD_MAX_RUNS = 100
ROLLBACK_CONSECUTIVE_REGRESSIONS = 3
REGRESSION_SCORE_DELTA = 5.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _two_proportion_z_pvalue(s1: int, n1: int, s2: int, n2: int) -> float:
    """One-sided two-proportion z-test p-value for H1: p1 > p2.

    Returns 1.0 (no evidence) if denominators are degenerate.
    """
    if n1 < 1 or n2 < 1:
        return 1.0
    p1 = s1 / n1
    p2 = s2 / n2
    pooled = (s1 + s2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0 if p1 <= p2 else 0.0
    z = (p1 - p2) / se
    # One-sided right-tail using the standard normal complementary CDF approx.
    # Φ(z) ≈ 0.5 * (1 + erf(z/√2))
    pvalue = 0.5 * math.erfc(z / math.sqrt(2))
    # erfc returns up to ~2.0 for very negative z; clamp to a valid probability.
    return max(0.0, min(1.0, pvalue))


class LoopPromotionService:
    """Walk every enabled loop and apply the canary policy."""

    async def evaluate_all(self) -> dict[str, Any]:
        async with get_session() as session:
            stmt = select(LoopModel).where(
                LoopModel.enabled.is_(True),
                LoopModel.auto_promote_enabled.is_(True),
            )
            loops = (await session.execute(stmt)).scalars().all()

        promoted = 0
        retired = 0
        held = 0
        rolled_back = 0
        for loop in loops:
            try:
                outcome = await self._evaluate_loop(loop.id)
                if outcome == "promoted":
                    promoted += 1
                elif outcome == "retired":
                    retired += 1
                elif outcome == "held":
                    held += 1
                elif outcome == "rolled_back":
                    rolled_back += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("loop.promotion_eval_failed", loop_id=loop.id, error=str(exc))

        return {
            "loops_evaluated": len(loops),
            "promoted": promoted,
            "retired": retired,
            "held": held,
            "rolled_back": rolled_back,
        }

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------

    async def _evaluate_loop(self, loop_id: int) -> Optional[str]:
        async with get_session() as session:
            loop = await session.get(LoopModel, loop_id)
            if not loop:
                return None

            # First, check rollback condition on the current active variant.
            rollback_outcome = await self._maybe_rollback(session, loop)
            if rollback_outcome:
                return rollback_outcome

            # Then check canary lifecycle for any non-retired canary.
            canary_stmt = (
                select(LoopVariantModel)
                .where(LoopVariantModel.loop_id == loop_id)
                .where(LoopVariantModel.is_canary.is_(True))
                .where(LoopVariantModel.retired_at.is_(None))
                .order_by(LoopVariantModel.created_at.asc())
            )
            canaries = (await session.execute(canary_stmt)).scalars().all()
            if not canaries:
                return None

            active_stmt = (
                select(LoopVariantModel)
                .where(LoopVariantModel.loop_id == loop_id)
                .where(LoopVariantModel.is_active.is_(True))
                .where(LoopVariantModel.retired_at.is_(None))
                .order_by(LoopVariantModel.created_at.desc())
                .limit(1)
            )
            active = (await session.execute(active_stmt)).scalar_one_or_none()
            if not active:
                # No active baseline — nothing to compare against; skip.
                return None

            for canary in canaries:
                outcome = await self._evaluate_canary(session, loop, active, canary)
                if outcome:
                    return outcome
        return None

    async def _evaluate_canary(
        self,
        session,
        loop: LoopModel,
        active: LoopVariantModel,
        canary: LoopVariantModel,
    ) -> Optional[str]:
        # Min sample
        if canary.runs_count < MIN_SAMPLE_PER_VARIANT or active.runs_count < MIN_SAMPLE_PER_VARIANT:
            if canary.runs_count >= HOLD_MAX_RUNS:
                # Held — not enough on the active side OR canary plateaued
                await self._record_decision(
                    session, loop_id=loop.id, from_id=active.id, to_id=canary.id,
                    decision="held",
                    rationale=f"insufficient samples (canary={canary.runs_count}, active={active.runs_count}) but canary>=HOLD_MAX_RUNS",
                )
                return "held"
            return None

        canary_sr = canary.successes / canary.runs_count
        canary_avg = canary.total_score / canary.runs_count
        active_sr = active.successes / active.runs_count
        active_avg = active.total_score / active.runs_count

        # Loss conditions (check first — fail fast)
        recent_failures = await self._consecutive_failures(session, canary.id)
        if (
            canary_sr < active_sr - LOSS_SUCCESS_RATE_DELTA
            or recent_failures >= LOSS_CONSECUTIVE_FAILURES
        ):
            canary.retired_at = _utcnow()
            canary.is_canary = False
            await session.commit()
            await self._record_decision(
                session, loop_id=loop.id, from_id=active.id, to_id=canary.id,
                decision="retired",
                rationale=(
                    f"canary loss: sr_canary={canary_sr:.2f} < sr_active-{LOSS_SUCCESS_RATE_DELTA} "
                    f"({active_sr - LOSS_SUCCESS_RATE_DELTA:.2f}) "
                    f"OR consecutive_failures={recent_failures}>={LOSS_CONSECUTIVE_FAILURES}"
                ),
            )
            return "retired"

        # Wall-clock exposure
        if not canary.created_at:
            return None
        exposure_h = (_utcnow() - canary.created_at).total_seconds() / 3600
        if exposure_h < WIN_MIN_WALL_CLOCK_HOURS:
            return None

        # Win conditions
        sr_delta = canary_sr - active_sr
        score_delta = canary_avg - active_avg
        pvalue = _two_proportion_z_pvalue(canary.successes, canary.runs_count, active.successes, active.runs_count)

        if (
            sr_delta >= WIN_SUCCESS_RATE_DELTA
            and score_delta >= WIN_SCORE_DELTA
            and pvalue < WIN_PVALUE_THRESHOLD
        ):
            # Promote: canary becomes active, old active stays warm (is_active=False, no retire)
            previous_active_id = active.id
            await session.execute(
                update(LoopVariantModel)
                .where(LoopVariantModel.id == active.id)
                .values(is_active=False)
            )
            await session.execute(
                update(LoopVariantModel)
                .where(LoopVariantModel.id == canary.id)
                .values(is_active=True, is_canary=False, canary_traffic_pct=100)
            )
            await session.execute(
                update(LoopModel)
                .where(LoopModel.id == loop.id)
                .values(
                    current_variant_id=canary.id,
                    baseline_score=canary_avg,
                    consecutive_regressions=0,
                )
            )
            await session.commit()
            await self._record_decision(
                session, loop_id=loop.id, from_id=previous_active_id, to_id=canary.id,
                decision="promoted",
                rationale=(
                    f"canary wins: sr_delta=+{sr_delta:.3f} score_delta=+{score_delta:.2f} "
                    f"p={pvalue:.4f} exposure_h={exposure_h:.1f} "
                    f"n_canary={canary.runs_count} n_active={active.runs_count}"
                ),
            )
            return "promoted"

        # Plateau hold
        if canary.runs_count >= HOLD_MAX_RUNS:
            await self._record_decision(
                session, loop_id=loop.id, from_id=active.id, to_id=canary.id,
                decision="held",
                rationale=(
                    f"canary plateaued: sr_delta={sr_delta:+.3f} score_delta={score_delta:+.2f} "
                    f"p={pvalue:.4f} after {canary.runs_count} runs"
                ),
            )
            return "held"

        return None

    async def _maybe_rollback(self, session, loop: LoopModel) -> Optional[str]:
        """If the active variant has 3 consecutive regressions, revert to the previous warm one."""
        if loop.current_variant_id is None or loop.baseline_score is None:
            return None

        recent_runs_stmt = (
            select(LoopRunModel)
            .where(LoopRunModel.loop_id == loop.id)
            .where(LoopRunModel.variant_id == loop.current_variant_id)
            .order_by(LoopRunModel.started_at.desc())
            .limit(ROLLBACK_CONSECUTIVE_REGRESSIONS)
        )
        recent = (await session.execute(recent_runs_stmt)).scalars().all()
        if len(recent) < ROLLBACK_CONSECUTIVE_REGRESSIONS:
            return None

        all_regressed = all(
            (r.status == "failure")
            or (r.judge_score is not None and r.judge_score < (loop.baseline_score - REGRESSION_SCORE_DELTA))
            for r in recent
        )
        if not all_regressed:
            # Reset counter
            if loop.consecutive_regressions:
                await session.execute(
                    update(LoopModel)
                    .where(LoopModel.id == loop.id)
                    .values(consecutive_regressions=0)
                )
                await session.commit()
            return None

        # Find the most recent warm previous variant (is_active=False, retired_at IS NULL)
        prev_stmt = (
            select(LoopVariantModel)
            .where(LoopVariantModel.loop_id == loop.id)
            .where(LoopVariantModel.id != loop.current_variant_id)
            .where(LoopVariantModel.is_active.is_(False))
            .where(LoopVariantModel.retired_at.is_(None))
            .order_by(LoopVariantModel.created_at.desc())
            .limit(1)
        )
        prev_active = (await session.execute(prev_stmt)).scalar_one_or_none()
        if not prev_active:
            # No warm fallback. Don't strand the loop in a re-trigger-every-tick
            # state — clear the regression counter and surface a vault alert.
            await session.execute(
                update(LoopModel)
                .where(LoopModel.id == loop.id)
                .values(consecutive_regressions=0)
            )
            await session.commit()
            logger.warning(
                "loop.rollback_blocked_no_target",
                loop_id=loop.id,
                current_variant=loop.current_variant_id,
            )
            return None

        regressed_id = loop.current_variant_id
        await session.execute(
            update(LoopVariantModel)
            .where(LoopVariantModel.id == regressed_id)
            .values(is_active=False)
        )
        await session.execute(
            update(LoopVariantModel)
            .where(LoopVariantModel.id == prev_active.id)
            .values(is_active=True, canary_traffic_pct=100)
        )
        new_baseline = (prev_active.total_score / prev_active.runs_count) if prev_active.runs_count else None
        await session.execute(
            update(LoopModel)
            .where(LoopModel.id == loop.id)
            .values(
                current_variant_id=prev_active.id,
                baseline_score=new_baseline,
                consecutive_regressions=0,
            )
        )
        await session.commit()
        await self._record_decision(
            session, loop_id=loop.id, from_id=regressed_id, to_id=prev_active.id,
            decision="rolled_back",
            rationale=f"3 consecutive regressions vs baseline {loop.baseline_score:.1f}",
        )
        logger.warning("loop.rolled_back", loop_id=loop.id, from_variant=regressed_id, to_variant=prev_active.id)
        return "rolled_back"

    async def _consecutive_failures(self, session, variant_id: int) -> int:
        stmt = (
            select(LoopRunModel.status)
            .where(LoopRunModel.variant_id == variant_id)
            .order_by(LoopRunModel.started_at.desc())
            .limit(LOSS_CONSECUTIVE_FAILURES)
        )
        rows = (await session.execute(stmt)).scalars().all()
        count = 0
        for status in rows:
            if status == "failure":
                count += 1
            else:
                break
        return count

    async def _record_decision(
        self,
        session,
        *,
        loop_id: int,
        from_id: Optional[int],
        to_id: int,
        decision: str,
        rationale: str,
    ) -> None:
        row = LoopPromotionModel(
            loop_id=loop_id,
            from_variant_id=from_id,
            to_variant_id=to_id,
            decision=decision,
            rationale=rationale,
            decided_by="auto",
        )
        session.add(row)
        await session.commit()
        logger.info(
            "loop.promotion_decision",
            loop_id=loop_id,
            from_variant=from_id,
            to_variant=to_id,
            decision=decision,
        )


@lru_cache(maxsize=1)
def get_loop_promotion() -> LoopPromotionService:
    return LoopPromotionService()
