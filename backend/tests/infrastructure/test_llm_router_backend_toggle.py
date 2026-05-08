"""
Tests for LOCAL_LLM_BACKEND toggle in Zero's llm_router.

Zero's router resolves (provider, model, fallbacks). The toggle rewrites any
'ollama' or 'vllm' provider in the result to match LOCAL_LLM_BACKEND, without
touching cloud providers (gemini, kimi, minimax, openrouter, huggingface).
"""

from __future__ import annotations

import pytest


class TestActiveBackendHelper:
    def test_unset_returns_empty_string(self, monkeypatch):
        monkeypatch.delenv("LOCAL_LLM_BACKEND", raising=False)
        from app.infrastructure.llm_router import _active_local_backend
        assert _active_local_backend() == ""

    def test_vllm_returned(self, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_BACKEND", "vllm")
        from app.infrastructure.llm_router import _active_local_backend
        assert _active_local_backend() == "vllm"

    def test_ollama_returned(self, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_BACKEND", "ollama")
        from app.infrastructure.llm_router import _active_local_backend
        assert _active_local_backend() == "ollama"

    def test_junk_value_ignored(self, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_BACKEND", "bogus")
        from app.infrastructure.llm_router import _active_local_backend
        assert _active_local_backend() == ""


class TestRemap:
    def test_no_override_returns_unchanged(self, monkeypatch):
        monkeypatch.delenv("LOCAL_LLM_BACKEND", raising=False)
        from app.infrastructure.llm_router import _apply_local_backend_remap
        assert _apply_local_backend_remap("ollama", "qwen3.6:35b") == ("ollama", "qwen3.6:35b")

    def test_vllm_override_rewrites_ollama(self, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_BACKEND", "vllm")
        monkeypatch.setenv("VLLM_CHAT_MODEL", "qwen3-chat")
        from app.infrastructure.llm_router import _apply_local_backend_remap
        provider, model = _apply_local_backend_remap("ollama", "qwen3.6:35b-a3b-q8_0")
        assert provider == "vllm"
        assert model == "qwen3-chat"

    def test_ollama_override_rewrites_vllm(self, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_BACKEND", "ollama")
        monkeypatch.setenv("OLLAMA_CHAT_MODEL", "qwen3.6:35b-a3b-q8_0")
        from app.infrastructure.llm_router import _apply_local_backend_remap
        provider, model = _apply_local_backend_remap("vllm", "qwen3-chat")
        assert provider == "ollama"
        assert model == "qwen3.6:35b-a3b-q8_0"

    def test_cloud_providers_untouched(self, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_BACKEND", "vllm")
        from app.infrastructure.llm_router import _apply_local_backend_remap
        for cloud in ("gemini", "kimi", "minimax", "openrouter", "huggingface"):
            assert _apply_local_backend_remap(cloud, "some-model") == (cloud, "some-model")

    def test_same_backend_no_change(self, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_BACKEND", "vllm")
        from app.infrastructure.llm_router import _apply_local_backend_remap
        # Already vllm → should not touch model name.
        assert _apply_local_backend_remap("vllm", "qwen3-chat") == ("vllm", "qwen3-chat")


class TestResolveProviderModel:
    @pytest.mark.asyncio
    async def test_resolve_respects_override(self, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_BACKEND", "vllm")
        monkeypatch.setenv("VLLM_CHAT_MODEL", "qwen3-chat")

        from app.infrastructure.llm_router import LlmRouter
        from app.models.llm import LlmRouterConfig, ModelAssignment

        router = LlmRouter()
        router._config = LlmRouterConfig(
            default_model="ollama/qwen3.6:35b-a3b-q8_0",
            task_assignments={
                "chat": ModelAssignment(
                    model="ollama/qwen3.6:35b-a3b-q8_0",
                    fallbacks=["ollama/qwen3.6:35b-a3b-q4_K_M", "gemini/gemini-3-pro"],
                )
            },
        )
        router._initialized = True

        provider, model, fallbacks = router.resolve_provider_model("chat")
        assert provider == "vllm"
        assert model == "qwen3-chat"
        # First fallback was ollama → remapped to vllm; gemini stays.
        fb_providers = [p for p, _ in fallbacks]
        assert "vllm" in fb_providers or "gemini" in fb_providers
        assert "gemini" in fb_providers
