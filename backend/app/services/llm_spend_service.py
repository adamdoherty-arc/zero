"""Monthly rollup of metered LLM spend from the llm_usage table.

Zero's own API calls (Bifrost / vLLM / provider APIs) land in `llm_usage` with
`cost_usd` per call. This service aggregates them by calendar month so the
bookkeeper can post one reviewable "metered AI spend" draft per period —
complementing the flat-rate subscriptions (Claude Max, ChatGPT, Cursor) that
never touch `llm_usage` and live in the recurring registry instead.

A plain SELECT SUM is deliberate: Zero's call volume doesn't justify porting
ADA's Redis-counter pipeline (llm_usage_tracker.py).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import structlog
from sqlalchemy import func, select

from app.db.models import LlmUsageModel
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)


class LlmSpendService:
    async def monthly_spend(self, *, months: int = 12) -> list[dict[str, Any]]:
        """Per-month cost/call totals with a by-provider breakdown, newest first."""
        months = max(1, min(int(months or 12), 60))
        period = func.to_char(func.date_trunc("month", LlmUsageModel.created_at), "YYYY-MM")
        async with get_session() as session:
            rows = (
                await session.execute(
                    select(
                        period.label("period"),
                        LlmUsageModel.provider,
                        func.count(LlmUsageModel.id).label("calls"),
                        func.coalesce(func.sum(LlmUsageModel.cost_usd), 0).label("cost"),
                    )
                    .group_by("period", LlmUsageModel.provider)
                    .order_by(period.desc())
                )
            ).all()

        by_period: dict[str, dict[str, Any]] = {}
        for row in rows:
            bucket = by_period.setdefault(
                row.period, {"period": row.period, "cost_usd": 0.0, "calls": 0, "by_provider": {}}
            )
            cost = float(row.cost or 0.0)
            bucket["cost_usd"] = round(bucket["cost_usd"] + cost, 4)
            bucket["calls"] += int(row.calls or 0)
            bucket["by_provider"][row.provider or "unknown"] = round(cost, 4)

        ordered = sorted(by_period.values(), key=lambda b: b["period"], reverse=True)
        return ordered[:months]

    async def spend_for_period(self, period: str) -> float:
        """Total metered cost for one YYYY-MM period."""
        month_expr = func.to_char(func.date_trunc("month", LlmUsageModel.created_at), "YYYY-MM")
        async with get_session() as session:
            total = (
                await session.execute(
                    select(func.coalesce(func.sum(LlmUsageModel.cost_usd), 0)).where(
                        month_expr == period
                    )
                )
            ).scalar()
        return round(float(total or 0.0), 4)


@lru_cache(maxsize=1)
def get_llm_spend_service() -> LlmSpendService:
    return LlmSpendService()
