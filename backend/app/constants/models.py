"""
Active model registry — single source of truth for Bifrost-prefixed model
strings. Anything that hardcodes a model name should import from here.

If a future migration renames a model, this file is the one place to update.
"""

from __future__ import annotations

# ---- Local LLM (chat) ----------------------------------------------------
# Served by shared-infra/vllm-chat. Bifrost vllm-local provider routes to
# http://vllm-chat:8000 — model must match what vLLM is actually serving.
# Running model (2026-05-25 verified): Qwen3-32B-AWQ.
LOCAL_CHAT = "vllm-local/Qwen3-32B-AWQ"

# ---- Local embeddings -----------------------------------------------------
LOCAL_EMBED = "embed-local/Qwen/Qwen3-Embedding-0.6B"

# ---- Whisper STT ---------------------------------------------------------
# Used by both reachy_realtime.local_handler and voice_loop_service via the
# REACHY_LOCAL_WHISPER_MODEL env var (this is the documented default).
WHISPER_STT = "distil-large-v3"

# ---- Kimi (cloud LLM) ----------------------------------------------------
# Kimi K2.5/K2.6 require temperature=1 EXACTLY; bifrost_provider clamps it.
KIMI_K2 = "moonshot/kimi-k2.6"

# ---- Vision (VLM) --------------------------------------------------------
# Primary: Moonshot's vision-capable SKU through Bifrost. Fallback: FreeLLM
# tier (Gemini 3.1 Flash if the router's priority chain picks it — note that
# freellmapi as deployed currently ignores explicit model spec and routes by
# health/quota priority; the request is best-effort).
# Local Qwen2-VL-2B is wired but parked (vllm-vlm container) until GPU
# headroom frees up (Qwen3-32B-AWQ leaves ~3 GB short on a 32 GB card).
VLM_CLOUD = "moonshot/moonshot-v1-32k-vision-preview"
VLM_FREELLM = "gemini-3-flash-preview"  # requested model -- freellmapi router decides actual route
VLM_LOCAL = "vllm-vlm/Qwen2-VL-2B-Instruct-AWQ"  # parked
