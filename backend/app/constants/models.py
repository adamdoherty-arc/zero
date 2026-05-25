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
# Primary: NVIDIA Build (free credits, 9 vision models incl Nemotron-Nano-12B-VL
# + Llama 4 Maverick + Llama 3.2 Vision). Direct OpenAI-compatible API at
# integrate.api.nvidia.com — bypasses Bifrost since their vk admin rejects
# custom provider names. Set NV_API_KEY in env to enable.
# Fallback 1 (parked): Moonshot vision through Bifrost — Kimi account was
# suspended for insufficient balance on 2026-05-25, all vision calls returned
# 429 with exceeded_current_quota_error.
# Fallback 2: FreeLLM (Gemini 3.1 Flash if router picks it -- best-effort).
# Local Qwen2-VL-2B is wired but parked (vllm-vlm container) until GPU
# headroom frees up.
VLM_NVIDIA = "nvidia/nemotron-nano-12b-v2-vl"  # PRIMARY
VLM_CLOUD = "moonshot/moonshot-v1-32k-vision-preview"  # parked (account suspended 2026-05-25)
VLM_FREELLM = "gemini-3-flash-preview"  # FreeLLM router may not honor this
VLM_LOCAL = "vllm-vlm/Qwen2-VL-2B-Instruct-AWQ"  # parked (GPU memory)
