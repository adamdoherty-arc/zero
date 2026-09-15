"""
Active model registry — single source of truth for Bifrost-prefixed model
strings. Anything that hardcodes a model name should import from here.

If a future migration renames a model, this file is the one place to update.
"""

from __future__ import annotations

# ---- Local LLM (chat) ----------------------------------------------------
# Served by shared-infra/qwen38-chat (Migration-20, 2026-08-31). Bifrost's
# vllm-local provider routes to http://qwen38-chat:18020 (host 18801).
# qwen3-chat is the STABLE gateway alias — Bifrost remaps it (and every other
# legacy name) to whatever the engine currently serves (qwen3.8-27b, 65K ctx,
# tools), so local model swaps never require a Zero code change again.
LOCAL_CHAT = "vllm-local/qwen3-chat"

# ---- Local embeddings -----------------------------------------------------
LOCAL_EMBED = "embed-local/Qwen/Qwen3-Embedding-0.6B"

# ---- Whisper STT ---------------------------------------------------------
# Used by both reachy_realtime.local_handler and voice_loop_service via the
# REACHY_LOCAL_WHISPER_MODEL env var (this is the documented default).
WHISPER_STT = "distil-large-v3"

# ---- Kimi (cloud LLM) ----------------------------------------------------
# Kimi K2.5/K2.6 require temperature=1 EXACTLY; bifrost_provider clamps it.
# 2026-09-15: Bifrost parked BOTH the paid Moonshot account's `moonshot/`
# provider AND its NIM-compat-shim successor — neither resolves on the
# gateway any more. Kimi K2.6 is now served through `hf-router`'s Moonshot AI
# mirror. Per-project affinity: Zero's primary cloud pool is Groq (see
# CLOUD_FAST/CLOUD_REASON below, Gemini Flash retired alongside it); Kimi is
# ADA's lane — keep Zero's Kimi usage low-volume.
KIMI_K2 = "hf-router/moonshotai/Kimi-K2.6"

# ---- Zero's cloud affinity pool (2026-06-11) ------------------------------
# Per-project affinity so the three projects don't drain each other's free
# rate limits: Legion→NVIDIA NIM (GLM-5.1/DeepSeek), ADA→Kimi K2.6 via NIM,
# Zero→Groq gpt-oss-120b (200K tok/day) + NVIDIA NIM lightning as fallback.
# 2026-06-15 (Fix-116): GEMINI_API_KEY went 401 (malformed/expired); 2026-09-15
# Bifrost parked the `gemini` provider entirely (governance-level park, not a
# key issue any more) — there is no live Gemini route left on the gateway, so
# the fallback is NVIDIA NIM's lightning tier instead of "restore the key".
CLOUD_FAST = "groq/openai/gpt-oss-120b"
CLOUD_FAST_FALLBACK = "nvidia-nim/nvidia/nemotron-3.5-lightning-30b-a3b"
CLOUD_REASON = "groq/openai/gpt-oss-120b"

# ---- Vision (VLM) --------------------------------------------------------
# Primary: NVIDIA Build (free credits, 9 vision models incl Nemotron-Nano-12B-VL
# + Llama 4 Maverick + Llama 3.2 Vision). Direct OpenAI-compatible API at
# integrate.api.nvidia.com — bypasses Bifrost since their vk admin rejects
# custom provider names. Set NV_API_KEY in env to enable.
# Fallback 1: Llama 3.2 Vision through Bifrost's nvidia-nim provider.
# Moonshot vision was parked 2026-05-25 (suspended account) and Bifrost's
# `moonshot` provider itself was parked entirely 2026-09-15 — no Moonshot
# vision route exists any more at any layer.
# Fallback 2: FreeLLM (glm-4.7-flash if router picks it -- best-effort; the
# freellmapi catalog has no dedicated vision model, same caveat as before
# when this was pointed at Gemini, which Bifrost has since parked too).
# Local Qwen2-VL-2B is wired but parked (vllm-vlm container) until GPU
# headroom frees up.
VLM_NVIDIA = "nvidia/nemotron-nano-12b-v2-vl"  # PRIMARY
VLM_CLOUD = "nvidia-nim/meta/llama-3.2-11b-vision-instruct"  # fallback 1, via Bifrost
VLM_FREELLM = "glm-4.7-flash"  # FreeLLM router may not honor this
VLM_LOCAL = "vllm-vlm/Qwen2-VL-2B-Instruct-AWQ"  # parked (GPU memory)
