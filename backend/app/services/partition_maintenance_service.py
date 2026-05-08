"""Partition maintenance for native Postgres partitioned tables (W6).

Creates next-month partitions ahead of time so inserts never hit the DEFAULT
partition (which is slow and a sign that rotation is falling behind).

Currently manages:
  - character_carousels (partitioned by RANGE(created_at), monthly)

Called by the scheduler job `carousel_partition_maintenance` (runs on the 25th
of each month and at app startup). Idempotent: CREATE IF NOT EXISTS makes it
safe to run on every tick.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from typing import List

import structlog
from sqlalchemy import text

from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)


_PARTITIONED_TABLES: List[str] = ["character_carousels"]
_LOOKAHEAD_MONTHS = 3


class PartitionMaintenanceService:
    async def ensure_future_partitions(self) -> dict:
        """Create partitions for the next N months on all managed tables.

        Returns a summary dict with per-table partition creation counts.
        """
        created_total = 0
        per_table: dict = {}
        for table in _PARTITIONED_TABLES:
            partitioned = await self._is_partitioned(table)
            if not partitioned:
                logger.info("partition_maintenance_skip_non_partitioned", table=table)
                per_table[table] = {"partitioned": False, "created": 0}
                continue
            created = await self._ensure_for_table(table)
            per_table[table] = {"partitioned": True, "created": created}
            created_total += created

        logger.info("partition_maintenance_complete", created=created_total, per_table=per_table)
        return {"created": created_total, "tables": per_table}

    async def _is_partitioned(self, table: str) -> bool:
        async with get_session() as session:
            res = await session.execute(
                text(
                    "SELECT EXISTS ("
                    "  SELECT 1 FROM pg_partitioned_table pt "
                    "  JOIN pg_class c ON c.oid = pt.partrelid "
                    "  WHERE c.relname = :table_name"
                    ")"
                ),
                {"table_name": table},
            )
            return bool(res.scalar())

    async def _ensure_for_table(self, table: str) -> int:
        """Create the next _LOOKAHEAD_MONTHS monthly partitions for `table`.

        Partition naming: {table}_YYYY_MM. Bounds are month start (inclusive)
        to next month start (exclusive), matching the existing convention set
        up by the 036_carousel_partitioning.sql migration.
        """
        today = date.today().replace(day=1)
        created = 0
        cur = today
        async with get_session() as session:
            for _ in range(_LOOKAHEAD_MONTHS + 1):
                nxt = _next_month(cur)
                partition_name = f"{table}_{cur.strftime('%Y_%m')}"
                ddl = text(
                    f"CREATE TABLE IF NOT EXISTS {partition_name} PARTITION OF {table} "
                    f"FOR VALUES FROM ('{cur.isoformat()}') TO ('{nxt.isoformat()}')"
                )
                try:
                    await session.execute(ddl)
                    created += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "partition_create_failed",
                        table=table,
                        partition=partition_name,
                        error=str(exc)[:150],
                    )
                cur = nxt
            await session.commit()
        return created


def _next_month(d: date) -> date:
    # First day of next month
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


@lru_cache()
def get_partition_maintenance_service() -> PartitionMaintenanceService:
    return PartitionMaintenanceService()
