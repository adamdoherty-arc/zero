"""
Active model registry — single source of truth for Bifrost-prefixed model
strings. Anything that hardcodes a model name should import from here.

If a future migration renames a model, this file is the one place to update.
"""

from __future__ import annotations

# ---- Local LLM (chat) ----------------------------------------------------
# Served by shared-infra/vllm-chat (vLLM 0.19 + Qwen3-32B-AWQ + Marlin
# kernels). Routed through Bifrost provider `vllm-local`.
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
# Moonshot's vision-capable SKU. Local Qwen2-VL-2B is wired but parked
# (vllm-vlm container) until GPU headroom frees up.
VLM_CLOUD = "moonshot/moonshot-v1-32k-vision-preview"
VLM_LOCAL = "vllm-vlm/Qwen2-VL-2B-Instruct-AWQ"  # parked
