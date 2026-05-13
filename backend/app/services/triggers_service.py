"""
Triggers — declarative event→action rules layered on integrations.

Storage: ``backend/app/data/triggers/rules.json`` (one big JSON list).
Recent firings are kept in-memory (last 200) so the UI can show them
without hitting the DB.

Predicate matching is intentionally simple:

    {"subject_contains": "invoice"}    → str.lower in payload["subject"]
    {"from": "boss@example.com"}       → exact match
    {"any_of": [{...}, {...}]}         → OR
    {"all_of": [{...}, {...}]}         → AND (also the implicit default)

Action shape:

    {"type": "vault_write", "params": {"source": "...", "body_template": "..."}}
    {"type": "tool", "params": {"name": "reachy.play_emotion", "args": {...}}}
    {"type": "webhook", "params": {"url": "https://...", "body": {...}}}
    {"type": "agent_prompt", "params": {"prompt": "..."}}
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import deque
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "triggers"
_RULES_FILE = "rules.json"
_MAX_FIRINGS = 200


def _predicate_match(predicate: dict, payload: dict) -> bool:
    if not predicate:
        return True
    if "any_of" in predicate:
        return any(_predicate_match(p, payload) for p in predicate["any_of"])
    if "all_of" in predicate:
        return all(_predicate_match(p, payload) for p in predicate["all_of"])
    for key, expected in predicate.items():
        if key.endswith("_contains"):
            field_name = key[:-len("_contains")]
            value = str(payload.get(field_name, "")).lower()
            if str(expected).lower() not in value:
                return False
        elif key.endswith("_equals"):
            field_name = key[:-len("_equals")]
            if payload.get(field_name) != expected:
                return False
        elif key.endswith("_in"):
            field_name = key[:-len("_in")]
            if payload.get(field_name) not in expected:
                return False
        else:
            if payload.get(key) != expected:
                return False
    return True


class TriggersService:
    def __init__(self) -> None:
        import app.services.triggers_service as _self_mod
        self._dir = _self_mod._DATA_DIR
        self._path = self._dir / _RULES_FILE
        self._rules: list[dict] = self._load()
        self._firings: deque[dict] = deque(maxlen=_MAX_FIRINGS)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def list_rules(self) -> list[dict]:
        return list(self._rules)

    async def create_rule(self, rule: dict) -> dict:
        rule = dict(rule)
        rule["id"] = uuid.uuid4().hex[:12]
        rule["created_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        self._rules.append(rule)
        await self._save()
        return rule

    async def update_rule(self, rule_id: str, updates: dict) -> Optional[dict]:
        for i, r in enumerate(self._rules):
            if r.get("id") == rule_id:
                merged = {**r, **updates, "id": rule_id}
                self._rules[i] = merged
                await self._save()
                return merged
        return None

    async def delete_rule(self, rule_id: str) -> bool:
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.get("id") != rule_id]
        if len(self._rules) == before:
            return False
        await self._save()
        return True

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def dispatch(self, event: str, payload: dict) -> list[dict]:
        """Find every enabled matching rule and execute its action.

        Returns the list of fired rule snapshots.
        """
        fired: list[dict] = []
        for rule in self._rules:
            if not rule.get("enabled", True):
                continue
            if rule.get("event") != event:
                continue
            if not _predicate_match(rule.get("predicate") or {}, payload or {}):
                continue
            result = await self._execute(rule, event, payload)
            firing = {
                "id": uuid.uuid4().hex[:10],
                "rule_id": rule.get("id"),
                "rule_name": rule.get("name"),
                "event": event,
                "payload": payload,
                "result": result,
                "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            }
            self._firings.appendleft(firing)
            fired.append(firing)
        return fired

    async def _execute(self, rule: dict, event: str, payload: dict) -> dict:
        action = rule.get("action") or {}
        kind = action.get("type")
        params = action.get("params") or {}
        try:
            if kind == "vault_write":
                from app.services.memory_tree import get_memory_tree
                tree = get_memory_tree()
                body = params.get("body_template", "")
                body = body.format(**payload) if body else json.dumps(payload, indent=2)
                paths = await tree.write_chunk(
                    params.get("source") or rule.get("name", "triggers"),
                    body,
                    title=params.get("title") or f"trigger {rule.get('name')}",
                    tags=["trigger"],
                )
                return {"type": "vault_write", "paths": [str(p) for p in paths]}

            if kind == "tool":
                # Stub — wire to reachy_realtime.tools.dispatch when available.
                logger.info(
                    "trigger_tool_call",
                    tool=params.get("name"),
                    rule=rule.get("name"),
                )
                return {"type": "tool", "status": "stub", "params": params}

            if kind == "webhook":
                import httpx
                url = params.get("url")
                body = params.get("body") or {}
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(url, json={**body, "event": event, "payload": payload})
                return {"type": "webhook", "status_code": resp.status_code}

            if kind == "agent_prompt":
                # Write the prompt as a chunk so the next agent loop picks it up.
                from app.services.memory_tree import get_memory_tree
                await get_memory_tree().write_chunk(
                    "agent_inbox",
                    params.get("prompt") or json.dumps(payload),
                    title=f"prompt: {rule.get('name')}",
                    tags=["agent-inbox"],
                )
                return {"type": "agent_prompt", "status": "enqueued"}

            return {"type": kind, "status": "unknown_action"}
        except Exception as e:  # noqa: BLE001
            logger.warning("trigger_action_failed", rule=rule.get("name"), error=str(e))
            return {"type": kind, "status": "error", "error": str(e)}

    def recent(self, limit: int = 50) -> list[dict]:
        return list(self._firings)[:limit]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            return list(json.loads(self._path.read_text(encoding="utf-8")) or [])
        except Exception as e:  # noqa: BLE001
            logger.warning("triggers_rules_read_failed", error=str(e))
            return []

    async def _save(self) -> None:
        def _do_save() -> None:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._rules, indent=2), encoding="utf-8")

        await asyncio.get_event_loop().run_in_executor(None, _do_save)


@lru_cache(maxsize=1)
def get_triggers_service() -> TriggersService:
    return TriggersService()
