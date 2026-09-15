"""
Vision VLM service — OCR + scene description via the shared Bifrost gateway.

Routes OpenAI-shape vision chat-completion calls to `ZERO_VLLM_CHAT_URL`
(defaults to `http://host.docker.internal:4445/v1`, which is the Bifrost
gateway). The model is configurable via `ZERO_VLM_MODEL` and defaults to
`nvidia-nim/meta/llama-3.2-11b-vision-instruct` — Bifrost parked the
`moonshot` provider entirely on 2026-09-15, so Llama 3.2 Vision via
nvidia-nim is the live cloud vision route.

A local Qwen2-VL-2B path is wired in `shared-infra/docker-compose.vllm.yml`
under the `vllm-vlm` service + `vllm-vlm` Bifrost provider, but it can't
co-exist with `Qwen3-32B-AWQ` on a 32 GB GPU without weight pruning. Bring
up vllm-vlm + set ZERO_VLM_MODEL=vllm-vlm/Qwen2-VL-2B-Instruct-AWQ once a
bigger GPU or smaller brain frees ~3 GB of VRAM.

Callers:
  - ambient_vision_service (Phase 5 scheduler tick).
  - MCP describe_scene tool (Phase 6).
  - carousel_v2.cheap_vlm_router (character-content image verification).
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from typing import Optional

import httpx
import structlog

logger = structlog.get_logger()


DEFAULT_AMBIENT_PROMPT = (
    "Describe what you see in 1–2 sentences. Then, on a new line, "
    "prefix with `ACTIONABLE:` and a concise tag if the scene contains "
    "something the user likely wants captured as a task/note "
    "(sticky note, receipt, whiteboard, shelf price, calendar, stack of "
    "unopened mail, etc.). If nothing is actionable, say `ACTIONABLE: none`."
)


def _b64_data_uri(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")


class VisionVLMService:
    _instance: Optional["VisionVLMService"] = None

    def __init__(self) -> None:
        # Vision chain (set in __init__ based on what's available):
        #   - if NV_API_KEY: primary = NVIDIA Integrate direct (free credits,
        #     9 vision SKUs incl Nemotron-Nano-12B-VL / Llama 3.2 Vision).
        #   - else: primary = Bifrost (Moonshot vision SKU — currently parked
        #     because Kimi account was suspended 2026-05-25).
        # Fallback chain always includes FreeLLM as last resort.
        nv_key = os.getenv("NV_API_KEY") or os.getenv("NVIDIA_API_KEY") or ""
        from app.constants.models import VLM_NVIDIA, VLM_CLOUD
        if nv_key:
            self._base_url = "https://integrate.api.nvidia.com/v1"
            self._api_key = nv_key
            self._model = os.getenv("ZERO_VLM_MODEL", VLM_NVIDIA)
            self._primary_provider = "nvidia"
        else:
            self._base_url = (
                os.getenv("ZERO_VLLM_CHAT_URL")
                or os.getenv("ZERO_BIFROST_URL")
                or "http://host.docker.internal:4445/v1"
            ).rstrip("/")
            self._api_key = (
                os.getenv("ZERO_VLLM_API_KEY")
                or os.getenv("ZERO_BIFROST_API_KEY")
                or "EMPTY"
            )
            self._model = os.getenv("ZERO_VLM_MODEL", VLM_CLOUD)
            self._primary_provider = "bifrost"
        self._timeout = float(os.getenv("ZERO_VLM_TIMEOUT", "45"))
        self._semaphore = asyncio.Semaphore(int(os.getenv("ZERO_VLM_CONCURRENCY", "2")))
        # Diagnostic: surface why the last VLM call failed so callers / the
        # dashboard can show "VLM unavailable — Moonshot account suspended"
        # instead of a silent empty caption.
        self._last_failure: Optional[dict] = None

    @classmethod
    def get_instance(cls) -> "VisionVLMService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Low-level chat-completion helper
    # ------------------------------------------------------------------

    async def _post_chat(
        self,
        base_url: str,
        api_key: str,
        model: str,
        prompt: str,
        jpeg: bytes,
        *,
        max_tokens: int,
        temperature: float,
    ) -> tuple[int, dict | None, str]:
        """Single HTTP attempt. Returns (status_code, parsed_json_or_None, error_preview)."""
        url = f"{base_url}/chat/completions"
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": _b64_data_uri(jpeg)}},
                    ],
                }
            ],
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, headers=headers, json=body)
            if resp.status_code >= 400:
                return resp.status_code, None, resp.text[:300]
            return resp.status_code, resp.json(), ""
        except Exception as e:
            return 0, None, str(e)[:200]

    async def _chat(
        self,
        prompt: str,
        jpeg: bytes,
        *,
        max_tokens: int = 256,
        temperature: float = 0.2,
    ) -> str:
        """Call the VLM with retry + FreeLLM fallback.

        Primary: ZERO_VLM_MODEL via Bifrost (Moonshot vision SKU by default).
        On 429/5xx, retry up to 3 times with exponential backoff (1s, 2s, 4s).
        On final primary failure, attempt FreeLLM (best-effort -- the router's
        priority chain may pick a text-only model and 4xx the image content,
        in which case we log and surface the diagnostic so callers know).
        """
        async with self._semaphore:
            # ---- Primary: Bifrost-routed VLM with backoff on transients ----
            primary_max_attempts = 3
            for attempt in range(primary_max_attempts):
                status, data, err = await self._post_chat(
                    self._base_url, self._api_key, self._model,
                    prompt, jpeg, max_tokens=max_tokens, temperature=temperature,
                )
                if data is not None:
                    try:
                        return (data["choices"][0]["message"]["content"] or "").strip()
                    except Exception:
                        logger.warning("vision_vlm_bad_response", raw=str(data)[:300])
                        return ""
                transient = status in (429, 502, 503, 504) or status == 0
                logger.warning(
                    "vision_vlm_http_error",
                    status=status,
                    attempt=attempt + 1,
                    transient=transient,
                    body_preview=err,
                    model=self._model,
                )
                if transient and attempt < primary_max_attempts - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                break

            primary_reason = self._classify_failure(err)
            primary_status_capture = status
            primary_err_capture = err

            # ---- Fallback 1: NVIDIA Integrate API direct ----
            # Skip if NVIDIA is already the primary (no point retrying same endpoint).
            nv_key = os.getenv("NV_API_KEY") or os.getenv("NVIDIA_API_KEY") or ""
            if nv_key and self._primary_provider != "nvidia":
                from app.constants.models import VLM_NVIDIA
                nv_status, nv_data, nv_err = await self._post_chat(
                    "https://integrate.api.nvidia.com/v1", nv_key, VLM_NVIDIA,
                    prompt, jpeg, max_tokens=max_tokens, temperature=temperature,
                )
                if nv_data is not None:
                    try:
                        logger.info("vision_vlm_nvidia_ok", model=VLM_NVIDIA)
                        self._last_failure = None
                        return (nv_data["choices"][0]["message"]["content"] or "").strip()
                    except Exception:
                        logger.warning("vision_vlm_nvidia_bad_response", raw=str(nv_data)[:300])
                else:
                    logger.warning("vision_vlm_nvidia_failed", status=nv_status, body_preview=nv_err)

            # ---- Fallback 2: FreeLLM (priority chain, may not honor vision spec) ----
            freellm_base = os.getenv("ZERO_FREELLM_BASE_URL", "http://shared-freellmapi:3001/v1").rstrip("/")
            freellm_token = os.getenv("ZERO_FREELLM_BEARER_TOKEN") or os.getenv("FREELLM_BEARER_TOKEN") or ""
            if freellm_token:
                from app.constants.models import VLM_FREELLM
                fl_status, fl_data, fl_err = await self._post_chat(
                    freellm_base, freellm_token, VLM_FREELLM,
                    prompt, jpeg, max_tokens=max_tokens, temperature=temperature,
                )
                if fl_data is not None:
                    try:
                        logger.info("vision_vlm_freellm_ok", model=VLM_FREELLM)
                        self._last_failure = None
                        return (fl_data["choices"][0]["message"]["content"] or "").strip()
                    except Exception:
                        logger.warning("vision_vlm_freellm_bad_response", raw=str(fl_data)[:300])
                else:
                    logger.warning("vision_vlm_freellm_failed", status=fl_status, body_preview=fl_err)

            # All providers failed — record diagnostic
            self._last_failure = {
                "primary_model": self._model,
                "primary_status": primary_status_capture,
                "primary_reason": primary_reason,
                "primary_body_preview": primary_err_capture,
                "nvidia_attempted": bool(nv_key),
                "freellm_attempted": bool(freellm_token),
            }
            return ""

    @staticmethod
    def _classify_failure(body_preview: str) -> str:
        """Map upstream error bodies to a short stable reason code."""
        if not body_preview:
            return "unreachable"
        low = body_preview.lower()
        if "insufficient balance" in low or "exceeded_current_quota" in low or "suspended" in low:
            return "account_suspended"
        if "no keys found that support model" in low:
            return "model_not_allowlisted"
        if "rate" in low and "limit" in low:
            return "rate_limited"
        if "401" in body_preview or "unauthorized" in low:
            return "auth_failed"
        if "400" in body_preview:
            return "bad_request"
        return "upstream_error"

    def last_failure(self) -> Optional[dict]:
        return self._last_failure

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        """Coarse health — does the endpoint look reachable?"""
        return bool(self._base_url)

    async def describe_scene(
        self,
        jpeg: bytes,
        prompt: Optional[str] = None,
    ) -> dict:
        """
        Returns a structured dict:
          {
            "caption": str,         # free-form description
            "actionable": str|None, # e.g. "sticky note", "receipt", or None
            "raw": str,             # full VLM output (for debugging)
            "model": str,
          }
        """
        if not jpeg:
            return {"caption": "", "actionable": None, "raw": "", "model": self._model}
        text = await self._chat(prompt or DEFAULT_AMBIENT_PROMPT, jpeg, max_tokens=220)
        caption, actionable = self._split_actionable(text)
        return {
            "caption": caption,
            "actionable": actionable,
            "raw": text,
            "model": self._model,
        }

    async def answer_about_scene(
        self,
        jpeg: bytes,
        question: str,
    ) -> str:
        """Answer a specific question grounded in the current frame."""
        if not jpeg:
            return ""
        prompt = (
            f"Answer this question based on the image. Be concise (1–2 sentences).\n\n"
            f"Question: {question}"
        )
        return await self._chat(prompt, jpeg, max_tokens=200)

    async def tag_objects(self, jpeg: bytes) -> list[str]:
        """Return a short list of salient object/topic tags."""
        if not jpeg:
            return []
        prompt = (
            "List up to 8 salient objects/topics in this image as a JSON array of "
            "short lowercase strings. Output ONLY the JSON array, nothing else."
        )
        text = await self._chat(prompt, jpeg, max_tokens=120)
        # Try to pull out a JSON array even if the model added prose around it.
        try:
            start = text.find("[")
            end = text.rfind("]")
            if start >= 0 and end > start:
                arr = json.loads(text[start : end + 1])
                if isinstance(arr, list):
                    return [str(x).strip().lower() for x in arr if x][:8]
        except Exception:
            pass
        return [w.strip().lower() for w in text.splitlines() if w.strip()][:8]

    # ------------------------------------------------------------------
    # Output parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _split_actionable(text: str) -> tuple[str, Optional[str]]:
        if not text:
            return "", None
        caption = text
        actionable: Optional[str] = None
        for line in text.splitlines():
            stripped = line.strip()
            upper = stripped.upper()
            if upper.startswith("ACTIONABLE:"):
                tag = stripped.split(":", 1)[1].strip()
                if tag and tag.lower() != "none":
                    actionable = tag
                caption = text.replace(line, "").strip()
                break
        return caption, actionable


def get_vision_vlm_service() -> VisionVLMService:
    return VisionVLMService.get_instance()
