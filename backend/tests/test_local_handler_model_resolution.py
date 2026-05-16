"""Regression tests for `resolve_chat_model` (local_handler.py).

Bug observed 2026-05-15: when the saved model name (`qwen3-chat`) did not
match the router's prefixed catalog name (`vllm-local/qwen3-chat`), the old
inline fallback picked `available_models[0]` — which on the Bifrost router
happened to be the embedding model (`embed-local/Qwen/Qwen3-Embedding-0.6B`).
The user saw "Switching to 'embed-local/...' for this session," and any
generated turn would have routed at a model that cannot do chat completion.

These tests pin two invariants:

1. A bare model name (`qwen3-chat`) MUST resolve to a router-prefixed
   counterpart (`vllm-local/qwen3-chat`) without surfacing a fallback notice
   — that case is a config drift, not a user error.
2. When fallback IS necessary, embedding-only models must be excluded so
   we never route chat completions at an embedding endpoint.
"""

from app.services.reachy_realtime.local_handler import resolve_chat_model


def test_direct_match_no_fallback():
    resolved, reason = resolve_chat_model(
        "vllm-local/qwen3-chat",
        ["vllm-local/qwen3-chat", "embed-local/Qwen/Qwen3-Embedding-0.6B"],
    )
    assert resolved == "vllm-local/qwen3-chat"
    assert reason is None


def test_suffix_match_resolves_silently():
    """`qwen3-chat` saved, router serves `vllm-local/qwen3-chat` — that's a
    config drift, not a user error. The handler must NOT emit a 'switching
    to' transcript for this case."""
    resolved, reason = resolve_chat_model(
        "qwen3-chat",
        ["embed-local/Qwen/Qwen3-Embedding-0.6B", "vllm-local/qwen3-chat"],
    )
    assert resolved == "vllm-local/qwen3-chat"
    assert reason is None, "suffix-match should be silent, not a fallback"


def test_fallback_excludes_embedding_models():
    """If the chat model is genuinely missing, we MUST pick a chat-capable
    fallback — never an embedding model, even if it's available_models[0]."""
    resolved, reason = resolve_chat_model(
        "qwen3-heretic-9b",
        [
            "embed-local/Qwen/Qwen3-Embedding-0.6B",
            "vllm-local/qwen3-chat",
        ],
    )
    assert resolved == "vllm-local/qwen3-chat"
    assert reason is not None and "qwen3-heretic-9b" in reason


def test_preferred_chat_model_wins():
    """When the preferred list includes an available chat model, prefer it
    over whatever happens to be first in available_models."""
    resolved, reason = resolve_chat_model(
        "ghost-model",
        [
            "openai/gpt-3.5-turbo",
            "embed-local/Qwen/Qwen3-Embedding-0.6B",
            "vllm-local/qwen3-chat",
        ],
        preferred=["vllm-local/qwen3-chat", "qwen3-chat"],
    )
    assert resolved == "vllm-local/qwen3-chat"
    assert reason is not None


def test_no_chat_model_returns_none():
    """An all-embedding catalog must NOT silently fall back to an embedding
    endpoint — the caller emits an error frame and aborts."""
    resolved, reason = resolve_chat_model(
        "qwen3-chat",
        ["embed-local/Qwen/Qwen3-Embedding-0.6B"],
    )
    assert resolved is None
    assert reason and "chat" in reason.lower()


def test_empty_catalog_returns_none():
    resolved, reason = resolve_chat_model("qwen3-chat", [])
    assert resolved is None
    assert reason is not None
