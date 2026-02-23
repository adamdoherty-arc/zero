"""
Metrics collection service for ZERO.

Tracks operational metrics in-memory (24h ring buffer) with hourly PostgreSQL snapshots.
Provides aggregated data for the system health dashboard.
"""

import time
from collections import deque
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from functools import lru_cache
import structlog

logger = structlog.get_logger()

# Maximum entries per metric in the ring buffer (24h at 1/min = 1440)
MAX_BUFFER_SIZE = 1500


class MetricsService:
    """In-memory metrics collection with PostgreSQL persistence."""

    def __init__(self):
        self._buffers: Dict[str, deque] = {}
        self._counters: Dict[str, int] = {}
        self._gauges: Dict[str, float] = {}

    def record(self, name: str, value: float, tags: Optional[Dict] = None):
        """Record a timestamped metric value."""
        if name not in self._buffers:
            self._buffers[name] = deque(maxlen=MAX_BUFFER_SIZE)
        self._buffers[name].append({
            "ts": time.time(),
            "value": value,
            "tags": tags or {},
        })

    def increment(self, name: str, amount: int = 1):
        """Increment a counter."""
        self._counters[name] = self._counters.get(name, 0) + amount

    def gauge(self, name: str, value: float):
        """Set a gauge value (current state)."""
        self._gauges[name] = value

    def get_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get aggregated metrics for the last N hours."""
        cutoff = time.time() - (hours * 3600)
        summary = {}

        for name, buf in self._buffers.items():
            recent = [e for e in buf if e["ts"] >= cutoff]
            if not recent:
                continue

            values = [e["value"] for e in recent]
            values.sort()

            summary[name] = {
                "count": len(values),
                "avg": sum(values) / len(values) if values else 0,
                "min": values[0] if values else 0,
                "max": values[-1] if values else 0,
                "p50": values[len(values) // 2] if values else 0,
                "p95": values[int(len(values) * 0.95)] if values else 0,
                "p99": values[int(len(values) * 0.99)] if values else 0,
            }

        return {
            "period_hours": hours,
            "timestamp": datetime.utcnow().isoformat(),
            "metrics": summary,
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
        }

    def get_timeseries(self, name: str, hours: int = 24, resolution_minutes: int = 5) -> List[Dict]:
        """Get time-bucketed data for a specific metric (for charts)."""
        if name not in self._buffers:
            return []

        cutoff = time.time() - (hours * 3600)
        bucket_size = resolution_minutes * 60
        recent = [e for e in self._buffers[name] if e["ts"] >= cutoff]

        if not recent:
            return []

        # Bucket by time
        buckets: Dict[int, List[float]] = {}
        for entry in recent:
            bucket_key = int(entry["ts"] // bucket_size) * bucket_size
            if bucket_key not in buckets:
                buckets[bucket_key] = []
            buckets[bucket_key].append(entry["value"])

        return [
            {
                "timestamp": datetime.utcfromtimestamp(ts).isoformat(),
                "avg": sum(vals) / len(vals),
                "count": len(vals),
                "max": max(vals),
            }
            for ts, vals in sorted(buckets.items())
        ]

    async def persist_snapshot(self):
        """Persist current metrics summary to PostgreSQL for historical analysis."""
        try:
            from app.infrastructure.database import get_session
            from sqlalchemy import text

            summary = self.get_summary(hours=1)

            async with get_session() as session:
                await session.execute(
                    text(
                        "INSERT INTO metrics_snapshots (timestamp, metrics_data, period) "
                        "VALUES (:ts, :data::jsonb, :period)"
                    ),
                    {
                        "ts": datetime.utcnow(),
                        "data": str(summary).replace("'", '"'),
                        "period": "hourly",
                    },
                )

            # Prune old snapshots (keep 30 days)
            async with get_session() as session:
                await session.execute(
                    text(
                        "DELETE FROM metrics_snapshots "
                        "WHERE timestamp < :cutoff"
                    ),
                    {"cutoff": datetime.utcnow() - timedelta(days=30)},
                )

            logger.debug("metrics_snapshot_persisted")
        except Exception as e:
            logger.warning("metrics_snapshot_failed", error=str(e))


@lru_cache()
def get_metrics_service() -> MetricsService:
    """Get singleton MetricsService instance."""
    return MetricsService()
