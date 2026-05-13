"""
Tests for hint-based LLM routing aliases.

Hints are coarse task descriptors (hint:summarize, hint:reasoning, etc.)
that map to existing task_assignments. Presets bias local-eligible hints
toward or away from local providers.
"""

from __future__ import annotations

import pytest


class TestParseHint:
    def test_empty_returns_none(self):
        from app.infrastructure.llm_hints import parse_hint
        assert parse_hint(None) is None
        assert parse_hint("") is None
        assert parse_hint("   ") is None

    def test_with_prefix(self):
        from app.infrastructure.llm_hints import parse_hint
        assert parse_hint("hint:summarize") == "summarize"
        assert parse_hint("hint:REACTION") == "reaction"

    def test_without_prefix(self):
        from app.infrastructure.llm_hints import parse_hint
        assert parse_hint("summarize") == "summarize"


class TestLocalEligibility:
    @pytest.mark.parametrize("hint", [
        "reaction", "classify", "format", "sentiment",
        "summarize", "medium", "tool_lite", "reflection",
    ])
    def test_local_eligible_hints(self, hint):
        from app.infrastructure.llm_hints import is_local_eligible
        assert is_local_eligible(hint)
        assert is_local_eligible(f"hint:{hint}")

    @pytest.mark.parametrize("hint", ["reasoning", "agentic", "coding", "vision"])
    def test_cloud_only_hints_not_local_eligible(self, hint):
        from app.infrastructure.llm_hints import is_local_eligible
        assert not is_local_eligible(hint)

    def test_unknown_hint_not_eligible(self):
        from app.infrastructure.llm_hints import is_local_eligible
        assert not is_local_eligible("phlogiston")


class TestHintToTaskType:
    def test_known_hint_maps_to_task_type(self):
        from app.infrastructure.llm_hints import resolve_hint_task_type
        assert resolve_hint_task_type("hint:summarize") == "summarization"
        assert resolve_hint_task_type("hint:classify") == "classification"
        assert resolve_hint_task_type("hint:reasoning") == "planning"

    def test_unknown_hint_falls_back_to_chat(self):
        from app.infrastructure.llm_hints import resolve_hint_task_type
        assert resolve_hint_task_type("hint:phlogiston") == "chat"


class TestPresetOverrides:
    def test_default_preset_no_override(self, monkeypatch):
        monkeypatch.delenv("ZERO_HINT_PRESET", raising=False)
        from app.infrastructure.llm_hints import resolve_hint_override
        assert resolve_hint_override("hint:summarize") is None

    def test_everything_local_forces_vllm(self, monkeypatch):
        monkeypatch.setenv("ZERO_HINT_PRESET", "everything_local")
        from app.infrastructure.llm_hints import resolve_hint_override
        assert resolve_hint_override("hint:summarize") == "vllm/qwen3-chat"
        assert resolve_hint_override("hint:reaction") == "vllm/qwen3-chat"

    def test_everything_local_does_not_touch_cloud_hints(self, monkeypatch):
        monkeypatch.setenv("ZERO_HINT_PRESET", "everything_local")
        from app.infrastructure.llm_hints import resolve_hint_override
        assert resolve_hint_override("hint:reasoning") is None
        assert resolve_hint_override("hint:coding") is None

    def test_embeddings_only_forces_cloud_for_chat_hints(self, monkeypatch):
        monkeypatch.setenv("ZERO_HINT_PRESET", "embeddings_only")
        from app.infrastructure.llm_hints import resolve_hint_override
        spec = resolve_hint_override("hint:summarize")
        assert spec and spec.startswith("kimi/")

    def test_memory_reflection_pulls_summarize_local(self, monkeypatch):
        monkeypatch.setenv("ZERO_HINT_PRESET", "memory_reflection")
        from app.infrastructure.llm_hints import resolve_hint_override
        assert resolve_hint_override("hint:summarize") == "vllm/qwen3-chat"
        assert resolve_hint_override("hint:reflection") == "vllm/qwen3-chat"
        # Non-memory hints unchanged on this preset
        assert resolve_hint_override("hint:format") is None

    def test_invalid_preset_logs_and_defaults(self, monkeypatch):
        monkeypatch.setenv("ZERO_HINT_PRESET", "wat")
        from app.infrastructure.llm_hints import get_current_preset, HintPreset
        assert get_current_preset() is HintPreset.DEFAULT


class TestRouterIntegration:
    def test_router_resolves_hint_strings(self, monkeypatch):
        monkeypatch.delenv("ZERO_HINT_PRESET", raising=False)
        from app.infrastructure.llm_router import get_llm_router
        llm = get_llm_router()
        # hint:summarize maps to task "summarization" which exists in defaults
        spec = llm.resolve("hint:summarize")
        assert spec  # non-empty, real model string
        # hint:classify maps to task "classification"
        spec2 = llm.resolve("hint:classify")
        assert spec2

    def test_router_honours_preset_override(self, monkeypatch):
        monkeypatch.setenv("ZERO_HINT_PRESET", "everything_local")
        from app.infrastructure.llm_router import get_llm_router
        llm = get_llm_router()
        assert llm.resolve("hint:summarize") == "vllm/qwen3-chat"

    def test_router_resolves_unknown_hint_to_chat_default(self, monkeypatch):
        monkeypatch.delenv("ZERO_HINT_PRESET", raising=False)
        from app.infrastructure.llm_router import get_llm_router
        llm = get_llm_router()
        # Unknown hint → falls through to chat task → has a model string
        assert llm.resolve("hint:phlogiston")

    def test_resolve_with_params_returns_assignment(self, monkeypatch):
        monkeypatch.delenv("ZERO_HINT_PRESET", raising=False)
        from app.infrastructure.llm_router import get_llm_router
        llm = get_llm_router()
        model, assignment = llm.resolve_with_params("hint:summarize")
        assert model
        assert assignment is not None
