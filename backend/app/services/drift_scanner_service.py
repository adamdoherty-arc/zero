"""Drift Scanner — runs the six SQL rules from drift_rules/ nightly.

SecondBrain Phase 5 §6. Each rule is a SELECT that returns rows with the
agent_alerts column shape. The scanner upserts distinct (rule, entity_id) rows
so the same alert doesn't re-fire noisily every night.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Optional

import structlog
from sqlalchemy import select, text, update

from app.db.models import AgentAlertModel
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)


_RULES_DIR = Path(__file__).parent / "drift_rules"


class DriftScannerService:
    def __init__(self) -> None:
        self._rules: list[tuple[str, str]] = []
        if _RULES_DIR.is_dir():
            for rule_file in sorted(_RULES_DIR.glob("*.sql")):
                self._rules.append((rule_file.stem, rule_file.read_text(encoding="utf-8")))

    async def scan_all(self) -> dict[str, Any]:
        created = 0
        fired_rules: list[str] = []
        errors: list[str] = []

        for rule_name, sql in self._rules:
            try:
                rows = await self._run_rule(rule_name, sql)
                fired_rules.append(f"{rule_name}:{len(rows)}")
                for row in rows:
                    if await self._upsert_alert(row):
                        created += 1
            except Exception as e:  # noqa: BLE001
                logger.warning("drift_rule_failed", rule=rule_name, error=str(e))
                errors.append(f"{rule_name}: {e}")

        logger.info("drift_scan_done", rules=fired_rules, created=created, errors=len(errors))
        return {
            "status": "ok" if not errors else "partial",
            "rules_count": len(self._rules),
            "fired_rules": fired_rules,
            "alerts_created": created,
            "errors": errors,
        }

    async def _run_rule(self, rule_name: str, sql: str) -> list[dict[str, Any]]:
        async with get_session() as session:
            result = await session.execute(text(sql))
            rows = result.mappings().all()
            return [dict(r) for r in rows]

    async def _upsert_alert(self, row: dict[str, Any]) -> bool:
        """Insert a new alert if one with the same (rule, entity_id, status=open) isn't already present."""
        rule = row.get("rule")
        entity_id = row.get("entity_id")

        async with get_session() as session:
            existing = await session.execute(
                select(AgentAlertModel.id).where(
                    AgentAlertModel.rule == rule,
                    AgentAlertModel.entity_id == entity_id,
                    AgentAlertModel.status == "open",
                )
            )
            if existing.scalar_one_or_none():
                return False
            session.add(
                AgentAlertModel(
                    id=f"alrt-{uuid.uuid4().hex[:12]}",
                    rule=rule,
                    severity=row.get("severity") or "info",
                    salience=float(row.get("salience") or 0.5),
                    entity_type=row.get("entity_type"),
                    entity_id=entity_id,
                    summary=row.get("summary") or rule,
                    details=row.get("details") or {},
                    status="open",
                )
            )
            await session.commit()
        return True


_singleton: Optional[DriftScannerService] = None


def get_drift_scanner() -> DriftScannerService:
    global _singleton
    if _singleton is None:
        _singleton = DriftScannerService()
    return _singleton
