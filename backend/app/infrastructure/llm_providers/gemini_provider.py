"""
Google Gemini provider via google-genai SDK.

Primary model: gemini-3.1-flash for cheap multimodal; gemini-3.1-pro for high-stakes prose.
Circuit breaker protected. Only active if ZERO_GEMINI_API_KEY is set.
"""

from typing import AsyncIterator, Dict, List

import structlog

from app.infrastructure.circuit_breaker import get_circuit_breaker
from app.infrastructure.config import get_settings
from app.infrastructure.llm_providers.base import BaseLLMProvider

logger = structlog.get_logger(__name__)

# Pricing per 1M tokens (USD). Project rule (CLAUDE.md "Always use the
# latest model") prefers 3.1; ``gemini-2.5-flash-lite`` is the cheapest
# stable vision-capable SKU on the v1beta endpoint until 3.1 GA flash ships.
GEMINI_PRICING = {
    "gemini-3.1-pro": {"input": 2.00, "output": 12.00},
    "gemini-3.1-flash": {"input": 0.10, "output": 0.40},
    "gemini-3.1-flash-lite": {"input": 0.025, "output": 0.10},
    "gemini-2.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-2.5-flash-lite": {"input": 0.025, "output": 0.10},
    # Rolling aliases — Google maintains these as pointers to the current
    # release; pricing here matches whatever they currently point at.
    "gemini-latest": {"input": 0.075, "output": 0.30},
    "gemini-flash-latest": {"input": 0.075, "output": 0.30},
    "gemini-flash-lite-latest": {"input": 0.025, "output": 0.10},
    # Preview / older entries kept so tests + legacy code don't bomb on
    # missing pricing (router falls back to DEFAULT_PRICING on miss anyway).
    "gemini-3.1-pro-preview": {"input": 2.00, "output": 12.00},
    "gemini-3-pro-preview": {"input": 1.25, "output": 5.00},
    "gemini-3-flash-preview": {"input": 0.10, "output": 0.40},
}
DEFAULT_PRICING = {"input": 2.00, "output": 12.00}

# Google deprecated the ``-preview`` IDs that some callsites still hand us
# (``gemini-3.1-pro``, ``gemini-3.1-flash``, etc.). Remap to the rolling
# ``-latest`` aliases that always point at the current GA flagship/lite.
# Keeping this at the provider boundary means we don't have to touch every
# downstream caller — they keep using the friendly tier name and get the
# real model under the hood.
_DEPRECATED_TO_LATEST: Dict[str, str] = {
    "gemini-3.1-pro": "gemini-pro-latest",
    "gemini-3.1-pro-preview": "gemini-pro-latest",
    "gemini-3-pro": "gemini-pro-latest",
    "gemini-3-pro-preview": "gemini-pro-latest",
    "gemini-3.1-flash": "gemini-flash-latest",
    "gemini-3.1-flash-preview": "gemini-flash-latest",
    "gemini-3-flash": "gemini-flash-latest",
    "gemini-3-flash-preview": "gemini-flash-latest",
    "gemini-3.1-flash-lite": "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite-preview": "gemini-flash-lite-latest",
}


def _resolve_gemini_model(model: str) -> str:
    """Map any deprecated Gemini ID to its current rolling alias."""
    return _DEPRECATED_TO_LATEST.get(model, model)


def _attach_images_to_last_user(
    messages: List[Dict[str, str]], image_urls: List[str]
) -> List[Dict]:
    """Append OpenAI-style ``image_url`` parts to the trailing user message.
    ``_convert_messages`` then translates the content-array into Gemini
    inline_data parts, so callers can hand us images in the same shape they'd
    use for Kimi / OpenRouter.
    """
    if not image_urls:
        return messages
    out: List[Dict] = []
    for m in messages[:-1]:
        out.append(m)
    last = messages[-1] if messages else {"role": "user", "content": ""}
    if last.get("role") != "user":
        out.append(last)
        out.append({
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": u}} for u in image_urls],
        })
        return out
    text = last.get("content", "")
    parts: List[Dict] = []
    if text and isinstance(text, str):
        parts.append({"type": "text", "text": text})
    elif isinstance(text, list):
        parts.extend(text)
    for url in image_urls:
        parts.append({"type": "image_url", "image_url": {"url": url}})
    out.append({"role": "user", "content": parts})
    return out


def _gemini_part_from_url(url: str):
    """Convert an http(s) URL or data URL into a Gemini inline_data part dict.

    Gemini's ``file_data`` part requires a Google-hosted URI (Files API or
    GCS) — it does NOT fetch arbitrary http(s) URLs. So we download the
    bytes ourselves and pass as ``inline_data``.

    Returns None on any error so the caller can drop the offending image
    without blowing up the whole request.
    """
    if not url:
        return None
    try:
        if url.startswith("data:"):
            # data:<mime>;base64,<payload>
            head, _, payload = url.partition(",")
            mime = "image/jpeg"
            if ";" in head:
                mime = head[5:].split(";", 1)[0] or mime
            import base64 as _b64
            return {"inline_data": {"mime_type": mime, "data": _b64.b64decode(payload)}}

        if url.startswith("http"):
            import httpx
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                resp = client.get(url)
                resp.raise_for_status()
                body = resp.content
            mime = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            if not mime.startswith("image/"):
                mime = "image/jpeg"
            return {"inline_data": {"mime_type": mime, "data": body}}
    except Exception:  # noqa: BLE001
        return None
    return None


class GeminiProvider(BaseLLMProvider):
    """Google Gemini API provider using the unified google-genai SDK."""

    def __init__(self):
        settings = get_settings()
        self._api_key = settings.gemini_api_key
        self._breaker = get_circuit_breaker(
            "llm_gemini",
            failure_threshold=5,
            recovery_timeout=120.0,
        )
        self._client = None

    def _get_client(self):
        """Lazy-init the google-genai client."""
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def _convert_messages(self, messages: List[Dict[str, str]]):
        """Convert standard messages to Gemini format.

        Returns (system_instruction, contents) where contents is a list
        of dicts with 'role' and 'parts' for the google-genai SDK.
        """
        system_parts = []
        contents = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                system_parts.append(content)
            elif role == "assistant":
                contents.append({"role": "model", "parts": [{"text": content}]})
            else:
                # User content may already be an OpenAI-style content array
                # (when an upstream caller pre-formatted images). Translate
                # those into the Gemini ``inline_data`` shape.
                if isinstance(content, list):
                    parts = []
                    for piece in content:
                        if not isinstance(piece, dict):
                            continue
                        ptype = piece.get("type")
                        if ptype == "text":
                            parts.append({"text": piece.get("text", "")})
                        elif ptype == "image_url":
                            url = (piece.get("image_url") or {}).get("url", "")
                            inline = _gemini_part_from_url(url)
                            if inline is not None:
                                parts.append(inline)
                    contents.append({"role": "user", "parts": parts or [{"text": ""}]})
                else:
                    contents.append({"role": "user", "parts": [{"text": content}]})

        return system_parts, contents

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        **kwargs,
    ) -> str:
        from google.genai import types

        client = self._get_client()

        # Top-level ``image_urls=`` kwarg: append each as an inline_data part
        # to the trailing user message. Carousel V2 Stage-8 calls in this form.
        image_urls = kwargs.get("image_urls") or []
        if image_urls:
            messages = _attach_images_to_last_user(messages, image_urls)

        system_parts, contents = self._convert_messages(messages)

        config_kwargs = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }

        # Native JSON mode
        if kwargs.get("json_mode"):
            config_kwargs["response_mime_type"] = "application/json"

        if system_parts:
            config_kwargs["system_instruction"] = "\n\n".join(system_parts)

        config = types.GenerateContentConfig(**config_kwargs)
        resolved_model = _resolve_gemini_model(model)
        if resolved_model != model:
            logger.debug("gemini_model_alias", requested=model, resolved=resolved_model)

        async def _call():
            response = await client.aio.models.generate_content(
                model=resolved_model,
                contents=contents,
                config=config,
            )
            return response.text

        return await self._breaker.call(_call)

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        **kwargs,
    ) -> AsyncIterator[str]:
        from google.genai import types

        client = self._get_client()
        system_parts, contents = self._convert_messages(messages)

        config_kwargs = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }

        if system_parts:
            config_kwargs["system_instruction"] = "\n\n".join(system_parts)

        config = types.GenerateContentConfig(**config_kwargs)
        resolved_model = _resolve_gemini_model(model)

        async for chunk in client.aio.models.generate_content_stream(
            model=resolved_model,
            contents=contents,
            config=config,
        ):
            if chunk.text:
                yield chunk.text

    async def is_healthy(self) -> bool:
        if not self._api_key:
            return False
        try:
            import asyncio

            async def _check():
                client = self._get_client()
                result = await client.aio.models.list()
                # result is a Pager; check if it has any models
                return bool(result and hasattr(result, 'page') and result.page)

            return await asyncio.wait_for(_check(), timeout=5.0)
        except Exception as e:
            logger.warning("gemini_health_check_failed", error=str(e))
            return False

    def estimate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str,
    ) -> float:
        pricing = GEMINI_PRICING.get(model, DEFAULT_PRICING)
        input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
        output_cost = (completion_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)
