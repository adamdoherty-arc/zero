"""
Vision VLM service — OCR + scene description via the shared Bifrost gateway.

Routes OpenAI-shape vision chat-completion calls to `ZERO_VLLM_CHAT_URL`
(defaults to `http://host.docker.internal:4445/v1`, which is the Bifrost
gateway in front of vllm-local / moonshot). The model name is configurable
via `ZERO_VLM_MODEL` (defaults to `moonshot/kimi-k2.6` post 2026-05-14).

Callers:
  - reachy_vision_service.analyze_scene() — fuses MediaPipe + VLM.
  - ambient_vision_service (Phase 5 scheduler tick).
  - MCP describe_scene tool (Phase 6).
  - reachy_chat_provider "what do you see?" intercept.
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
        # Post 2026-05-14 Bifrost migration: all LLM/VLM traffic exits via
        # the Bifrost gateway at :4445. Bifrost speaks the OpenAI vision
        # shape natively, but the policy permits only Kimi + local Qwen,
        # so the default model is now Bifrost's moonshot/kimi-k2.6. Set
        # ZERO_VLM_MODEL to "vllm-local/qwen3-chat" (text-only) or a
        # future bifrost-prefixed local vision SKU to override.
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
        self._model = os.getenv("ZERO_VLM_MODEL", "moonshot/kimi-k2.6")
        self._timeout = float(os.getenv("ZERO_VLM_TIMEOUT", "45"))
        self._semaphore = asyncio.Semaphore(int(os.getenv("ZERO_VLM_CONCURRENCY", "2")))

    @classmethod
    def get_instance(cls) -> "VisionVLMService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Low-level chat-completion helper
    # ------------------------------------------------------------------

    async def _chat(
        self,
        prompt: str,
        jpeg: bytes,
        *,
        max_tokens: int = 256,
        temperature: float = 0.2,
    ) -> str:
        url = f"{self._base_url}/chat/completions"
        body = {
            "model": self._model,
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
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        async with self._semaphore:
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(url, headers=headers, json=body)
                if resp.status_code >= 400:
                    logger.warning(
                        "vision_vlm_http_error",
                        status=resp.status_code,
                        body_preview=resp.text[:300],
                    )
                    return ""
                data = resp.json()
            except Exception as e:
                logger.warning("vision_vlm_request_failed", error=str(e)[:200])
                return ""

        try:
            choice = data["choices"][0]
            return (choice["message"]["content"] or "").strip()
        except Exception:
            logger.warning("vision_vlm_bad_response", raw=str(data)[:300])
            return ""

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
