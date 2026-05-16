"""
Character image relevance scoring via Gemini Vision.

Given an image URL and a character name + universe + franchise, asks the
shared LiteLLM proxy (`gemini-flash-latest` alias) whether the image
actually depicts that character. Returns a 0.0-1.0 confidence score.

Used by `image_source_service.discover_images()` to demote irrelevant
high-quality images (the Thor failure mode: a sharp 1080p photo that
isn't actually Thor still passes resolution + face checks).

Routes through the same LiteLLM proxy as vision_vlm_service so the
model name is configurable via `ZERO_VLM_MODEL` and tracking flows
through the central LLM observability path.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
from typing import Any, Dict, Optional

import httpx
import structlog

logger = structlog.get_logger()


_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0 Safari/537.36"
)


async def _fetch_as_data_uri(url: str, timeout: float = 15.0) -> Optional[str]:
    """Download an image and return a ``data:image/jpeg;base64,...`` URI.

    LiteLLM/Gemini's URL fetcher is blocked by a number of common image hosts
    (Wikipedia 403s its UA, some CDNs require a Referer). Downloading
    ourselves with a browser UA dodges those — the data-URI is then accepted
    by every multimodal provider.
    """
    if not url:
        return None
    if url.startswith("data:"):
        return url
    try:
        headers = {"User-Agent": _BROWSER_UA, "Accept": "image/*,*/*;q=0.8"}
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers=headers,
        ) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return None
        content_type = (resp.headers.get("content-type") or "image/jpeg").split(";", 1)[0].strip()
        if not content_type.startswith("image/"):
            content_type = "image/jpeg"
        body = resp.content
        if not body or len(body) < 200:
            # Likely an error page, not a real image.
            return None
        return f"data:{content_type};base64,{base64.b64encode(body).decode('ascii')}"
    except Exception:  # noqa: BLE001
        return None


_PROMPT_TEMPLATE = (
    "Validate whether the attached image depicts a specific fictional "
    "character. Your entire response MUST be a single JSON object on one "
    "line. Do NOT write any preamble like \"Here is the JSON\" or "
    "\"Sure, here's\". Do NOT use markdown code fences. Do NOT add "
    "explanatory prose before or after. Start your response with "
    "the character `{{` and end with `}}`. Nothing else.\n\n"
    "Character name: {name}\n"
    "Universe: {universe}\n"
    "Franchise: {franchise}\n"
    "{description_block}"
    "Schema: {{\"match\": bool, \"confidence\": 0..1, \"reason\": \"<=15 words\"}}\n\n"
    "Set match=false (confidence <0.3) for: generic stock photos, the wrong "
    "character, watermarked collages with multiple figures, comic panels "
    "with unclear primary subject, mismatched actor headshots from unrelated "
    "films.\n"
    "Set match=true (confidence >=0.7) for: clear portrait or action shot, "
    "signature costume/features, official poster or promotional still, key "
    "art with this character as primary subject.\n"
    "Set match=true with confidence 0.5-0.7 for ambiguous group shots where "
    "the named character IS still recognizable as the subject.\n\n"
    "Output ONLY the JSON object."
)


def _strip_code_fences(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        end = len(lines)
        if lines and lines[-1].strip() == "```":
            end = -1
        text = "\n".join(lines[1:end]).strip()
    return text


def _parse_json_response(raw: str) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    cleaned = _strip_code_fences(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Find a balanced object substring.
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Best-effort recovery from truncated output: extract individual fields.
    out: Dict[str, Any] = {}
    m_match = re.search(r'"match"\s*:\s*(true|false)', cleaned, re.IGNORECASE)
    if m_match:
        out["match"] = m_match.group(1).lower() == "true"
    m_conf = re.search(r'"confidence"\s*:\s*([0-9.]+)', cleaned)
    if m_conf:
        try:
            out["confidence"] = float(m_conf.group(1))
        except ValueError:
            pass
    m_reason = re.search(r'"reason"\s*:\s*"([^"]*)', cleaned)
    if m_reason:
        out["reason"] = m_reason.group(1)
    return out or None


class CharacterImageRelevanceService:
    """Gemini Vision-based relevance scoring for character images."""

    _instance: Optional["CharacterImageRelevanceService"] = None

    def __init__(self) -> None:
        # Post 2026-05-14 Bifrost migration: all LLM/VLM traffic exits via
        # the Bifrost gateway at :4445. The legacy LiteLLM env var names
        # are kept as fallback lookups so a one-off override still works,
        # but the default is now the Bifrost endpoint.
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
        # Same alias as vision_vlm_service; LiteLLM remaps to current Gemini flash.
        self._model = os.getenv(
            "ZERO_CHARACTER_RELEVANCE_MODEL",
            os.getenv("ZERO_VLM_MODEL", "gemini-flash-latest"),
        )
        self._timeout = float(os.getenv("ZERO_CHARACTER_RELEVANCE_TIMEOUT", "25"))
        self._concurrency = int(os.getenv("ZERO_CHARACTER_RELEVANCE_CONCURRENCY", "3"))
        self._semaphore = asyncio.Semaphore(self._concurrency)

    @classmethod
    def get_instance(cls) -> "CharacterImageRelevanceService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def score_relevance(
        self,
        image_url: str,
        character_name: str,
        universe: str,
        franchise: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Score how confidently an image depicts the named character.

        Returns dict with:
          - score: float 0.0-1.0 (0.5 means "vision unavailable / unsure")
          - is_match: bool
          - reason: short explanation string
          - source: "vision" | "vision_unavailable" | "invalid_input"
        """
        if not image_url or not character_name:
            return {
                "score": 0.5,
                "is_match": False,
                "reason": "missing_input",
                "source": "invalid_input",
            }

        description_block = ""
        if description:
            snippet = description[:300].strip()
            if snippet:
                description_block = f"Description: {snippet}\n"

        prompt = _PROMPT_TEMPLATE.format(
            name=character_name,
            universe=universe or "unknown",
            franchise=franchise or universe or "unknown",
            description_block=description_block,
        )

        # Download bytes ourselves and pass as data-URI. LiteLLM's fetcher
        # is blocked by several common image hosts (Wikipedia, some CDNs);
        # base64 sidesteps that and all multimodal providers accept it.
        data_uri = await _fetch_as_data_uri(image_url)
        if not data_uri:
            return {
                "score": 0.5,
                "is_match": False,
                "reason": "image_fetch_failed",
                "source": "vision_unavailable",
            }

        # max_tokens=1024: gemini-3.x flash uses ~200 reasoning tokens before
        # generating output, so a tight budget truncates the JSON. response_format
        # is omitted because the LiteLLM proxy maps gemini-flash-latest to a
        # thinking model that ignores it on prompt-grounded tasks.
        body = {
            "model": self._model,
            "max_tokens": 1024,
            "temperature": 0.1,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_uri}},
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
                    resp = await client.post(
                        f"{self._base_url}/chat/completions",
                        headers=headers, json=body,
                    )
                if resp.status_code >= 400:
                    logger.warning(
                        "character_relevance_http_error",
                        status=resp.status_code,
                        body=resp.text[:200],
                        character=character_name,
                    )
                    return {
                        "score": 0.5,
                        "is_match": False,
                        "reason": f"http_{resp.status_code}",
                        "source": "vision_unavailable",
                    }
                data = resp.json()
            except Exception as e:  # noqa: BLE001 — vision must never block discovery
                logger.warning(
                    "character_relevance_request_failed",
                    error=str(e)[:200], character=character_name,
                )
                return {
                    "score": 0.5,
                    "is_match": False,
                    "reason": "request_failed",
                    "source": "vision_unavailable",
                }

        try:
            raw = (data["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError):
            return {
                "score": 0.5,
                "is_match": False,
                "reason": "bad_response_shape",
                "source": "vision_unavailable",
            }

        parsed = _parse_json_response(raw)
        if not isinstance(parsed, dict):
            logger.info(
                "character_relevance_unparseable",
                preview=raw[:200], character=character_name,
                length=len(raw),
            )
            return {
                "score": 0.5,
                "is_match": False,
                "reason": "unparseable",
                "source": "vision_unavailable",
            }

        is_match = bool(parsed.get("match", False))
        try:
            confidence = float(parsed.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        # Compose final score: a reject zeroes confidence even if model
        # disagreed with itself; an accept multiplies by stated confidence.
        score = confidence if is_match else min(confidence, 0.3)
        reason = str(parsed.get("reason", ""))[:120]

        return {
            "score": round(score, 3),
            "is_match": is_match,
            "reason": reason or ("match" if is_match else "rejected"),
            "source": "vision",
        }


def get_character_image_relevance_service() -> CharacterImageRelevanceService:
    return CharacterImageRelevanceService.get_instance()
