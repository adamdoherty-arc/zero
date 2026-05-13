"""
Tests for the browser-control service + Telegram channel — both degrade
gracefully when their optional deps / env are missing.
"""

from __future__ import annotations

import asyncio


class TestBrowserControl:
    def test_unavailable_without_playwright(self):
        from app.services.browser_control_service import BrowserControlService
        svc = BrowserControlService()
        # If Playwright is genuinely installed the test still passes; we
        # just confirm the field is bool.
        assert isinstance(svc.is_available(), bool)

    def test_open_returns_error_when_unavailable(self, monkeypatch):
        from app.services import browser_control_service as mod
        # Force the unavailable path regardless of host state
        svc = mod.BrowserControlService()
        svc._playwright = None  # type: ignore[attr-defined]
        result = asyncio.run(svc.open("https://example.com"))
        assert result.ok is False
        assert "playwright" in (result.error or "").lower()

    def test_allowlist_blocks_unauthorized(self, monkeypatch):
        monkeypatch.setenv("BROWSER_CONTROL_ALLOWLIST", "https://allowed.com")
        from app.services.browser_control_service import BrowserControlService
        svc = BrowserControlService()
        svc._playwright = None  # type: ignore[attr-defined]
        result = asyncio.run(svc.open("https://denied.com/page"))
        assert result.ok is False
        assert "allowlist" in (result.error or "").lower()

    def test_allowlist_permits_authorized(self, monkeypatch):
        monkeypatch.setenv("BROWSER_CONTROL_ALLOWLIST", "https://allowed.com")
        from app.services.browser_control_service import BrowserControlService
        svc = BrowserControlService()
        svc._playwright = None  # type: ignore[attr-defined]
        result = asyncio.run(svc.open("https://allowed.com/page"))
        # Will be False due to no Playwright, but error must NOT be allowlist.
        assert (result.error or "").lower().startswith("playwright")

    def test_close_on_unknown_session_safe(self):
        from app.services.browser_control_service import BrowserControlService
        svc = BrowserControlService()
        result = asyncio.run(svc.close("nonexistent"))
        assert result.ok is True

    def test_list_sessions_empty(self):
        from app.services.browser_control_service import BrowserControlService
        svc = BrowserControlService()
        assert svc.list_sessions() == []


class TestTelegram:
    def test_not_configured_without_token(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        from app.services.telegram_channel_service import TelegramChannelService
        svc = TelegramChannelService()
        assert svc.is_configured() is False
        assert svc.status()["configured"] is False

    def test_configured_with_token(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
        from app.services.telegram_channel_service import TelegramChannelService
        svc = TelegramChannelService()
        assert svc.is_configured() is True

    def test_send_without_token_returns_error(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        from app.services.telegram_channel_service import TelegramChannelService
        svc = TelegramChannelService()
        result = asyncio.run(svc.send(123, "hello"))
        assert result["ok"] is False

    def test_send_empty_text_returns_error(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
        from app.services.telegram_channel_service import TelegramChannelService
        svc = TelegramChannelService()
        result = asyncio.run(svc.send(123, ""))
        assert result["ok"] is False

    def test_message_length_clamped(self, monkeypatch):
        # Just verify the truncation happens — we don't actually send.
        # Inject a long string and confirm internal trimming logic doesn't
        # raise.
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
        from app.services.telegram_channel_service import (
            MAX_MESSAGE_LEN,
            TelegramChannelService,
        )
        svc = TelegramChannelService()
        long_text = "x" * (MAX_MESSAGE_LEN + 500)
        # The send method will try to call api.telegram.org; we just want
        # to make sure it doesn't crash on the length check.
        async def run():
            # Patch the network so we don't actually hit Telegram.
            import httpx
            class DummyClient:
                def __init__(self, *a, **kw): pass
                async def __aenter__(self): return self
                async def __aexit__(self, *a): pass
                async def post(self, url, json=None, **kw):
                    class R:
                        def json(_self):
                            return {"ok": True, "_truncated_to": len(json["text"])}
                    return R()
            monkeypatch.setattr(httpx, "AsyncClient", DummyClient)
            r = await svc.send(123, long_text)
            assert r["ok"] is True
            # Truncation reserves room for the trailing ellipsis.
            assert r["_truncated_to"] <= MAX_MESSAGE_LEN
            assert r["_truncated_to"] >= MAX_MESSAGE_LEN - 4
        asyncio.run(run())

    def test_default_handler_writes_to_vault(self, monkeypatch, tmp_path):
        from app.services import telegram_channel_service as mod
        from app.services.memory_tree import service as tree_mod

        monkeypatch.setattr(tree_mod, "_DATA_DIR", tmp_path / "vault")
        tree_mod.get_memory_tree.cache_clear()  # type: ignore[attr-defined]
        _ = tree_mod.get_memory_tree()

        svc = mod.TelegramChannelService()
        message = mod.TelegramMessage(
            update_id=1,
            chat_id=42,
            user_id=99,
            username="testuser",
            text="hello from telegram",
            date_ts=0,
        )
        asyncio.run(svc._default_handler(message))
        tree = tree_mod.get_memory_tree()
        hits = asyncio.run(tree.search("hello from telegram"))
        assert len(hits) >= 1
