"""
Outcome Learning Service for Zero Brain.

Tracks every decision and its measured outcome.
Computes per-strategy metrics, calibration accuracy, and synthesizes learnings.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
from functools import lru_cache

import structlog
from sqlalchemy import select, func as sql_func

from app.infrastructure.database import get_session
from app.infrastructure.unified_llm_client import get_unified_llm_client
from app.db.models import BrainOutcomeRecordModel
from app.models.brain import OutcomeRecord, StrategyMetrics, CalibrationBucket

logger = structlog.get_logger(__name__)


class OutcomeLearningService:
    """Tracks decisions and outcomes. Computes strategy metrics and calibration."""

    def _gen_id(self) -> str:
        return f"bo-{uuid.uuid4().hex[:12]}"

    async def record_outcome(
        self,
        domain: str,
        action_type: str,
        action_id: Optional[str] = None,
        strategy_used: Optional[str] = None,
        predicted_score: Optional[float] = None,
        actual_score: Optional[float] = None,
        metrics: Optional[Dict[str, Any]] = None,
        learnings: Optional[str] = None,
    ) -> str:
        """Record an outcome. Auto-extract learnings if actual_score provided."""
        record_id = self._gen_id()

        # Auto-extract learnings via LLM if we have both predicted and actual
        if learnings is None and actual_score is not None and predicted_score is not None:
            try:
                gap = actual_score - predicted_score
                direction = "exceeded expectations" if gap > 0 else "underperformed"
                llm = get_unified_llm_client()
                result = await llm.chat(
                    prompt=(
                        f"A {domain} action ({action_type}) using strategy '{strategy_used}' "
                        f"was predicted to score {predicted_score:.1f} but actually scored {actual_score:.1f} "
                        f"({direction} by {abs(gap):.1f} points). "
                        f"Metrics: {metrics or {}}. "
                        f"In one sentence, what's the key takeaway?"
                    ),
                    task_type="analysis",
                    temperature=0.2,
                    max_tokens=200,
                )
                learnings = result.strip() if result else None
            except Exception as e:
                logger.warning("outcome_learning_extraction_failed", error=str(e))

        try:
            async with get_session() as session:
                model = BrainOutcomeRecordModel(
                    id=record_id,
                    domain=domain,
                    action_type=action_type,
                    action_id=action_id,
                    strategy_used=strategy_used,
                    predicted_score=predicted_score,
                    actual_score=actual_score,
                    metrics=metrics or {},
                    learnings=learnings,
                    created_at=datetime.now(timezone.utc),
                )
                session.add(model)
                await session.commit()

            logger.info("outcome_recorded", id=record_id, domain=domain,
                       action_type=action_type, strategy=strategy_used)
            return record_id

        except Exception as e:
            logger.error("outcome_record_failed", error=str(e))
            raise

    async def get_strategy_metrics(
        self,
        domain: Optional[str] = None,
        strategy: Optional[str] = None,
        days: int = 30,
    ) -> List[StrategyMetrics]:
        """Per-strategy win rate, avg score, calibration error."""
        try:
            since = datetime.now(timezone.utc) - timedelta(days=days)
            async with get_session() as session:
                query = (
                    select(
                        BrainOutcomeRecordModel.strategy_used,
                        BrainOutcomeRecordModel.domain,
                        sql_func.count().label("total"),
                        sql_func.avg(BrainOutcomeRecordModel.actual_score).label("avg_score"),
                        sql_func.count().filter(
                            BrainOutcomeRecordModel.actual_score >= 60
                        ).label("wins"),
                    )
                    .where(BrainOutcomeRecordModel.created_at >= since)
                    .where(BrainOutcomeRecordModel.actual_score.isnot(None))
                    .where(BrainOutcomeRecordModel.strategy_used.isnot(None))
                    .group_by(
                        BrainOutcomeRecordModel.strategy_used,
                        BrainOutcomeRecordModel.domain,
                    )
                )

                if domain:
                    query = query.where(BrainOutcomeRecordModel.domain == domain)
                if strategy:
                    query = query.where(BrainOutcomeRecordModel.strategy_used == strategy)

                result = await session.execute(query)
                rows = result.all()

                metrics = []
                for row in rows:
                    total = row.total or 1
                    wins = row.wins or 0
                    avg = float(row.avg_score or 50)

                    # Calculate calibration error (MAE) for this strategy
                    cal_query = (
                        select(
                            sql_func.avg(
                                sql_func.abs(
                                    BrainOutcomeRecordModel.predicted_score -
                                    BrainOutcomeRecordModel.actual_score
                                )
                            )
                        )
                        .where(BrainOutcomeRecordModel.strategy_used == row.strategy_used)
                        .where(BrainOutcomeRecordModel.predicted_score.isnot(None))
                        .where(BrainOutcomeRecordModel.actual_score.isnot(None))
                        .where(BrainOutcomeRecordModel.created_at >= since)
                    )
                    cal_result = await session.execute(cal_query)
                    cal_error = float(cal_result.scalar() or 0)

                    metrics.append(StrategyMetrics(
                        strategy=row.strategy_used,
                        domain=row.domain,
                        total_uses=total,
                        win_rate=wins / total if total > 0 else 0,
                        avg_score=avg,
                        calibration_error=cal_error,
                        sample_size=total,
                    ))

                return sorted(metrics, key=lambda m: m.avg_score, reverse=True)

        except Exception as e:
            logger.error("strategy_metrics_failed", error=str(e))
            return []

    async def get_calibration_report(
        self,
        domain: Optional[str] = None,
        days: int = 30,
    ) -> List[CalibrationBucket]:
        """Bucket predicted scores into confidence ranges, compute accuracy per bucket."""
        try:
            since = datetime.now(timezone.utc) - timedelta(days=days)
            async with get_session() as session:
                query = (
                    select(
                        BrainOutcomeRecordModel.predicted_score,
                        BrainOutcomeRecordModel.actual_score,
                    )
                    .where(BrainOutcomeRecordModel.created_at >= since)
                    .where(BrainOutcomeRecordModel.predicted_score.isnot(None))
                    .where(BrainOutcomeRecordModel.actual_score.isnot(None))
                )
                if domain:
                    query = query.where(BrainOutcomeRecordModel.domain == domain)

                result = await session.execute(query)
                rows = result.all()

            # Bucket into ranges
            buckets = {
                "0-20": [], "20-40": [], "40-60": [], "60-80": [], "80-100": []
            }
            for predicted, actual in rows:
                if predicted < 20:
                    buckets["0-20"].append((predicted, actual))
                elif predicted < 40:
                    buckets["20-40"].append((predicted, actual))
                elif predicted < 60:
                    buckets["40-60"].append((predicted, actual))
                elif predicted < 80:
                    buckets["60-80"].append((predicted, actual))
                else:
                    buckets["80-100"].append((predicted, actual))

            report = []
            for label, pairs in buckets.items():
                if not pairs:
                    report.append(CalibrationBucket(
                        range_label=label, count=0,
                        avg_predicted=0, avg_actual=0, mae=0,
                    ))
                    continue

                avg_pred = sum(p for p, _ in pairs) / len(pairs)
                avg_act = sum(a for _, a in pairs) / len(pairs)
                mae = sum(abs(p - a) for p, a in pairs) / len(pairs)
                report.append(CalibrationBucket(
                    range_label=label,
                    count=len(pairs),
                    avg_predicted=round(avg_pred, 2),
                    avg_actual=round(avg_act, 2),
                    mae=round(mae, 2),
                ))

            return report

        except Exception as e:
            logger.error("calibration_report_failed", error=str(e))
            return []

    async def get_best_strategy(
        self,
        domain: str,
        action_type: str,
        min_samples: int = 5,
    ) -> Optional[str]:
        """Return the strategy with highest avg_score for a domain/action_type."""
        try:
            async with get_session() as session:
                query = (
                    select(
                        BrainOutcomeRecordModel.strategy_used,
                        sql_func.avg(BrainOutcomeRecordModel.actual_score).label("avg"),
                        sql_func.count().label("cnt"),
                    )
                    .where(BrainOutcomeRecordModel.domain == domain)
                    .where(BrainOutcomeRecordModel.action_type == action_type)
                    .where(BrainOutcomeRecordModel.actual_score.isnot(None))
                    .where(BrainOutcomeRecordModel.strategy_used.isnot(None))
                    .group_by(BrainOutcomeRecordModel.strategy_used)
                    .having(sql_func.count() >= min_samples)
                    .order_by(sql_func.avg(BrainOutcomeRecordModel.actual_score).desc())
                    .limit(1)
                )
                result = await session.execute(query)
                row = result.first()
                return row.strategy_used if row else None

        except Exception as e:
            logger.error("best_strategy_lookup_failed", error=str(e))
            return None

    async def extract_learnings(
        self,
        domain: Optional[str] = None,
        days: int = 7,
        limit: int = 10,
    ) -> List[str]:
        """Get stored learnings from recent outcomes."""
        try:
            since = datetime.now(timezone.utc) - timedelta(days=days)
            async with get_session() as session:
                query = (
                    select(BrainOutcomeRecordModel.learnings)
                    .where(BrainOutcomeRecordModel.created_at >= since)
                    .where(BrainOutcomeRecordModel.learnings.isnot(None))
                    .order_by(BrainOutcomeRecordModel.created_at.desc())
                    .limit(limit)
                )
                if domain:
                    query = query.where(BrainOutcomeRecordModel.domain == domain)

                result = await session.execute(query)
                return [row[0] for row in result.all() if row[0]]

        except Exception as e:
            logger.error("extract_learnings_failed", error=str(e))
            return []

    async def count(self, domain: Optional[str] = None) -> int:
        """Count total outcome records."""
        try:
            async with get_session() as session:
                query = select(sql_func.count(BrainOutcomeRecordModel.id))
                if domain:
                    query = query.where(BrainOutcomeRecordModel.domain == domain)
                result = await session.execute(query)
                return result.scalar() or 0
        except Exception:
            return 0

    async def get_recent(
        self,
        domain: Optional[str] = None,
        limit: int = 20,
    ) -> List[OutcomeRecord]:
        """Get recent outcome records."""
        try:
            async with get_session() as session:
                query = select(BrainOutcomeRecordModel).order_by(
                    BrainOutcomeRecordModel.created_at.desc()
                ).limit(limit)
                if domain:
                    query = query.where(BrainOutcomeRecordModel.domain == domain)

                result = await session.execute(query)
                rows = result.scalars().all()
                return [
                    OutcomeRecord(
                        id=r.id, domain=r.domain, action_type=r.action_type,
                        action_id=r.action_id, strategy_used=r.strategy_used,
                        predicted_score=r.predicted_score, actual_score=r.actual_score,
                        metrics=r.metrics or {}, learnings=r.learnings,
                        created_at=r.created_at,
                    )
                    for r in rows
                ]
        except Exception as e:
            logger.error("get_recent_outcomes_failed", error=str(e))
            return []


@lru_cache()
def get_outcome_learning_service() -> OutcomeLearningService:
    return OutcomeLearningService()
