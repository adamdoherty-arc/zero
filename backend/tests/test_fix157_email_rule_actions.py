"""Fix-157: the apply_label rule action never worked, and reported success anyway.

`_execute_apply_label` reached into `gmail._get_service()` -- a method that has
never existed on GmailService (the real one is `_get_gmail_service`). The
AttributeError was caught locally and returned as a plain dict, so it never
reached the dispatcher's `except`. The dispatcher then stamped
`status: "success"` unconditionally, so a rule action that did nothing at all
was indistinguishable from one that worked.

Verified live before the fix:
    {'message': "Failed to apply label: 'GmailService' object has no attribute '_get_service'"}
"""
from datetime import datetime

import pytest

from app.models.email_rule import (
    ConditionsBlock,
    EmailRule,
    RuleAction,
    RuleCondition,
)
from app.services.email_rule_service import get_email_rule_service
from app.services.gmail_service import GmailService


def _rule(action_type: str, params: dict | None = None) -> EmailRule:
    return EmailRule(
        id="test-rule",
        name="test",
        conditions=ConditionsBlock(
            conditions=[RuleCondition(field="sender", operator="contains", value="example.com")]
        ),
        actions=[RuleAction(type=action_type, params=params or {})],
        created_at=datetime.utcnow(),
    )


def test_gmail_service_exposes_apply_label():
    """The method the rule action calls must actually exist."""
    assert hasattr(GmailService, "apply_label")


def test_gmail_service_has_no_underscore_get_service():
    """Regression guard on the exact typo'd private method that was called."""
    assert not hasattr(GmailService, "_get_service")
    assert hasattr(GmailService, "_get_gmail_service")


@pytest.mark.asyncio
async def test_apply_label_failure_signals_success_false(monkeypatch):
    svc = get_email_rule_service()

    async def _fail(self, email_id, label_id):
        return False

    monkeypatch.setattr(GmailService, "apply_label", _fail, raising=True)
    result = await svc._execute_apply_label("mid", {"label": "INBOX"})
    assert result["success"] is False


@pytest.mark.asyncio
async def test_apply_label_success_has_no_failure_marker(monkeypatch):
    svc = get_email_rule_service()

    async def _ok(self, email_id, label_id):
        return True

    monkeypatch.setattr(GmailService, "apply_label", _ok, raising=True)
    result = await svc._execute_apply_label("mid", {"label": "INBOX"})
    assert result.get("success", True) is True


@pytest.mark.asyncio
async def test_dispatcher_marks_soft_failure_as_error(monkeypatch):
    """A handler returning success=False must NOT be recorded as a success."""
    svc = get_email_rule_service()

    async def _soft_fail(action, email_id, email_data):
        return {"message": "Failed to apply label 'INBOX'", "success": False}

    async def _noop_stats(rule_id):
        return None

    monkeypatch.setattr(svc, "_execute_action", _soft_fail, raising=True)
    monkeypatch.setattr(svc, "_increment_match_count", _noop_stats, raising=True)

    results = await svc.execute_actions(_rule("apply_label", {"label": "INBOX"}), "mid", {})
    assert results[0]["status"] == "error"


@pytest.mark.asyncio
async def test_dispatcher_still_marks_real_success(monkeypatch):
    svc = get_email_rule_service()

    async def _ok(action, email_id, email_data):
        return {"message": "Label 'INBOX' applied"}

    async def _noop_stats(rule_id):
        return None

    monkeypatch.setattr(svc, "_execute_action", _ok, raising=True)
    monkeypatch.setattr(svc, "_increment_match_count", _noop_stats, raising=True)

    results = await svc.execute_actions(_rule("apply_label", {"label": "INBOX"}), "mid", {})
    assert results[0]["status"] == "success"
