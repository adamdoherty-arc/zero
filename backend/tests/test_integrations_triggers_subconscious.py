"""
Tests for Composio provider + auto-fetch loop + triggers + subconscious.
These are pure-Python tests — none of them require Composio to actually be
installed or COMPOSIO_API_KEY to be set.
"""

from __future__ import annotations

import asyncio


class TestComposioProvider:
    def test_degrades_gracefully_without_sdk(self, monkeypatch):
        monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)
        from app.services.integrations.composio_provider import ComposioProvider
        provider = ComposioProvider()
        assert provider.is_available() is False
        items = provider.list_integrations()
        assert len(items) > 0
        # Every catalog entry should be present with `connected=false` by default
        for item in items:
            assert "id" in item
            assert "connected" in item

    def test_native_gmail_connect_requires_real_oauth(self, monkeypatch, tmp_path):
        monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)
        from app.services.integrations import composio_provider as cp_module
        from app.services import gmail_oauth_service

        class NoOAuth:
            async def has_valid_tokens(self, account_id=None):
                return False

        monkeypatch.setattr(
            gmail_oauth_service,
            "get_gmail_oauth_service",
            lambda: NoOAuth(),
        )
        monkeypatch.setattr(cp_module, "_DATA_DIR", tmp_path)
        provider = cp_module.ComposioProvider()
        result = asyncio.run(provider.connect("gmail"))
        assert result["status"] == "unavailable"
        assert "gmail" not in provider.list_connected()

    def test_stale_native_connection_is_not_trusted(self, monkeypatch, tmp_path):
        monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)
        from app.services.integrations import composio_provider as cp_module
        monkeypatch.setattr(cp_module, "_DATA_DIR", tmp_path)
        provider = cp_module.ComposioProvider()
        provider._connections["gmail"] = cp_module.Connection(  # type: ignore[attr-defined]
            integration_id="gmail",
            connection_id="native:gmail",
            connected_at="2026-05-13T00:00:00Z",
            extra={"verified_oauth": True},
        )
        gmail = next(item for item in provider.list_integrations() if item["id"] == "gmail")
        assert gmail["connected"] is False
        assert gmail["available"] is False
        assert "gmail" not in provider.list_connected()

    def test_disconnect_roundtrip(self, monkeypatch, tmp_path):
        monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)
        from app.services.integrations import composio_provider as cp_module
        monkeypatch.setattr(cp_module, "_DATA_DIR", tmp_path)
        provider = cp_module.ComposioProvider()
        provider._connections["gmail"] = cp_module.Connection(  # type: ignore[attr-defined]
            integration_id="gmail",
            connection_id="native:gmail",
            connected_at="2026-05-13T00:00:00Z",
            extra={
                "verified_oauth": True,
                "verified_oauth_source": "google_oauth_service",
            },
        )
        result = asyncio.run(provider.disconnect("gmail"))
        assert result["status"] == "disconnected"
        assert "gmail" not in provider.list_connected()


class TestAutoFetchLoop:
    def test_status_when_stopped(self):
        from app.services.integrations.auto_fetch_loop import AutoFetchLoop
        loop = AutoFetchLoop(interval_minutes=20)
        s = loop.status()
        assert s["running"] is False
        assert s["interval_minutes"] == 20

    def test_set_interval_clamps_low(self):
        from app.services.integrations.auto_fetch_loop import AutoFetchLoop
        loop = AutoFetchLoop()
        loop.set_interval(0)
        assert loop.status()["interval_minutes"] == 1

    def test_sync_unknown_integration(self):
        from app.services.integrations.auto_fetch_loop import AutoFetchLoop
        loop = AutoFetchLoop()
        result = asyncio.run(loop.sync_one("nonexistent_integration"))
        assert result["status"] in {"unknown_integration", "not_connected"}


class TestPredicateMatching:
    def test_simple_equality(self):
        from app.services.triggers_service import _predicate_match
        assert _predicate_match({"from": "x@y.com"}, {"from": "x@y.com"}) is True
        assert _predicate_match({"from": "x@y.com"}, {"from": "other@y.com"}) is False

    def test_contains(self):
        from app.services.triggers_service import _predicate_match
        assert (
            _predicate_match({"subject_contains": "invoice"}, {"subject": "Your INVOICE 2024"})
            is True
        )
        assert (
            _predicate_match({"subject_contains": "invoice"}, {"subject": "Hi"}) is False
        )

    def test_any_of(self):
        from app.services.triggers_service import _predicate_match
        pred = {"any_of": [{"from": "a@b"}, {"from": "c@d"}]}
        assert _predicate_match(pred, {"from": "a@b"}) is True
        assert _predicate_match(pred, {"from": "z@z"}) is False

    def test_all_of(self):
        from app.services.triggers_service import _predicate_match
        pred = {"all_of": [{"from": "a@b"}, {"priority_equals": "high"}]}
        assert _predicate_match(pred, {"from": "a@b", "priority": "high"}) is True
        assert _predicate_match(pred, {"from": "a@b", "priority": "low"}) is False

    def test_empty_predicate_matches(self):
        from app.services.triggers_service import _predicate_match
        assert _predicate_match({}, {"anything": "here"}) is True


class TestTriggersService:
    def test_crud(self, monkeypatch, tmp_path):
        from app.services.triggers_service import TriggersService
        monkeypatch.setattr(
            "app.services.triggers_service._DATA_DIR", tmp_path
        )
        svc = TriggersService()
        created = asyncio.run(
            svc.create_rule(
                {
                    "name": "test rule",
                    "event": "gmail.new_message",
                    "predicate": {"subject_contains": "test"},
                    "action": {"type": "vault_write", "params": {"source": "triggers"}},
                    "enabled": True,
                }
            )
        )
        assert created["id"]
        rules = svc.list_rules()
        assert len(rules) == 1
        updated = asyncio.run(
            svc.update_rule(created["id"], {**created, "enabled": False})
        )
        assert updated is not None
        assert updated["enabled"] is False
        ok = asyncio.run(svc.delete_rule(created["id"]))
        assert ok is True

    def test_dispatch_queues_approval_for_vault_write(self, monkeypatch, tmp_path):
        from app.services.triggers_service import TriggersService
        # Redirect both the trigger rules dir AND the vault root for isolation.
        monkeypatch.setattr(
            "app.services.triggers_service._DATA_DIR", tmp_path / "triggers"
        )
        monkeypatch.setattr(
            "app.services.memory_tree.service._DATA_DIR", tmp_path
        )
        # Reset the memory_tree singleton so it picks up the patched dir.
        from app.services.memory_tree import service as svc_mod
        svc_mod.get_memory_tree.cache_clear()  # type: ignore[attr-defined]

        svc = TriggersService()
        asyncio.run(
            svc.create_rule(
                {
                    "name": "invoice",
                    "event": "gmail.new_message",
                    "predicate": {"subject_contains": "invoice"},
                    "action": {
                        "type": "vault_write",
                        "params": {"source": "gmail-triggers", "title": "trigger fired"},
                    },
                    "enabled": True,
                }
            )
        )
        firings = asyncio.run(
            svc.dispatch("gmail.new_message", {"subject": "Your invoice"})
        )
        assert len(firings) == 1
        assert firings[0]["rule_name"] == "invoice"
        assert firings[0]["result"]["status"] == "approval_required"


class TestSubconsciousLoop:
    def test_status_when_idle(self):
        from app.services.subconscious_loop import SubconsciousLoop
        loop = SubconsciousLoop(interval_minutes=15)
        s = loop.status()
        assert s["running"] is False
        assert s["interval_minutes"] == 15

    def test_set_interval_clamps_low(self):
        from app.services.subconscious_loop import SubconsciousLoop
        loop = SubconsciousLoop()
        loop.set_interval(0)
        assert loop.status()["interval_minutes"] == 1

    def test_run_once_skips_when_no_activity(self, monkeypatch, tmp_path):
        from app.services.subconscious_loop import SubconsciousLoop
        monkeypatch.setattr(
            "app.services.memory_tree.service._DATA_DIR", tmp_path
        )
        from app.services.memory_tree import service as svc_mod
        svc_mod.get_memory_tree.cache_clear()  # type: ignore[attr-defined]

        loop = SubconsciousLoop()
        result = asyncio.run(loop.run_once())
        assert result["status"] in {"skipped", "llm_unavailable", "ok"}
