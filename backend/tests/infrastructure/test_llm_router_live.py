"""
Live integration tests for Zero's local LLM backend.

Auto-skips when the configured endpoint isn't reachable. Run explicitly:

    LOCAL_LLM_BACKEND=vllm pytest backend/tests/infrastructure/test_llm_router_live.py -v
"""

from __future__ import annotations

import os

import httpx
import pytest


def _backend_reachable() -> bool:
    backend = os.getenv("LOCAL_LLM_BACKEND", "").lower()
    if backend == "vllm":
        url = os.getenv("VLLM_CHAT_BASE_URL", "http://localhost:18800/v1").rstrip("/")
        probe = f"{url}/models"
    elif backend == "ollama":
        url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1").rstrip("/")
        probe = f"{url}/models"
    else:
        return False
    try:
        resp = httpx.get(probe, timeout=2.0)
        return resp.status_code == 200
    except Exception:
        return False


live = pytest.mark.skipif(not _backend_reachable(), reason="local LLM backend not reachable")


@live
def test_live_models_endpoint():
    backend = os.getenv("LOCAL_LLM_BACKEND", "").lower()
    if backend == "vllm":
        url = os.getenv("VLLM_CHAT_BASE_URL", "http://localhost:18800/v1").rstrip("/")
    else:
        url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    resp = httpx.get(f"{url}/models", timeout=5.0)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data.get("data"), list)


@live
@pytest.mark.asyncio
async def test_live_chat_via_provider():
    """End-to-end: go through the unified_llm_client stack with backend toggle."""
    from app.infrastructure.unified_llm_client import get_unified_llm_client

    client = get_unified_llm_client()
    result = await client.chat(
        prompt="Reply with only the word: ok",
        task_type="chat",
        max_tokens=16,
        temperature=0.0,
    )
    assert isinstance(result, str)
    assert len(result.strip()) >= 1
