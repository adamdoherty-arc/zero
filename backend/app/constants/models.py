"""
Active model registry — single source of truth for Bifrost-prefixed model
strings. Anything that hardcodes a model name should import from here.

If a future migration renames a model, this file is the one place to update.
"""

from __future__ import annotations

# ---- Local LLM (chat) ----------------------------------------------------
# Served by shared-infra/vllm-chat. Bifrost vllm-local provider routes to
# http://vllm-chat:8000. qwen3-chat is the STABLE gateway alias — Bifrost maps
# it (and the legacy "Qwen3-32B-AWQ" name) to whatever vllm-chat currently
# serves (Qwen3.5-35B-A3B GPTQ, 64K ctx, tools, since 2026-06-11), so local
# model swaps never require a Zero code change again.
LOCAL_CHAT = "vllm-local/qwen3-chat"

# ---- Local embeddings -----------------------------------------------------
LOCAL_EMBED = "embed-local/Qwen/Qwen3-Embedding-0.6B"

# ---- Whisper STT ---------------------------------------------------------
# Used by both reachy_realtime.local_handler and voice_loop_service via the
# REACHY_LOCAL_WHISPER_MODEL env var (this is the documented default).
WHISPER_STT = "distil-large-v3"

# ---- Kimi (cloud LLM) ----------------------------------------------------
# Kimi K2.5/K2.6 require temperature=1 EXACTLY; bifrost_provider clamps it.
# 2026-06-11: the paid Moonshot account was retired — Bifrost's `moonshot/`
# provider is now a compat shim over NVIDIA NIM's FREE Kimi K2.6 serving, so
# this string keeps working at $0. Per-project affinity: Zero's primary cloud
# pool is Gemini Flash + Groq (see CLOUD_FAST/CLOUD_REASON below); Kimi is
# ADA's lane — keep Zero's Kimi usage low-volume.
KIMI_K2 = "moonshot/kimi-k2.6"

# ---- Zero's cloud affinity pool (2026-06-11) ------------------------------
# Per-project affinity so the three projects don't drain each other's free
# rate limits: Legion→NVIDIA NIM (GLM-5.1/DeepSeek), ADA→Kimi K2.6 via NIM,
# Zero→Gemini Flash (1,500 req/day free) + Groq gpt-oss-120b (200K tok/day).
# 2026-06-15 (Fix-116): GEMINI_API_KEY went 401 (malformed/expired), so Groq
# is the working cloud primary until the key is restored. Gemini stays as the
# documented fallback — flip these back to gemini-first once the key is valid
# (gemini's 1,500 req/day free quota > groq's 1,000/day).
CLOUD_FAST = "groq/openai/gpt-oss-120b"
CLOUD_FAST_FALLBACK = "gemini/gemini-3.5-flash"
CLOUD_REASON = "groq/openai/gpt-oss-120b"

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
