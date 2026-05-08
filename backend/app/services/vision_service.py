"""
Vision Service — Process images from Reachy camera via multimodal LLM.

Capabilities:
- Describe what the camera sees
- Detect user presence
- Answer visual questions ("what's on my desk?")

2026-04-28: stripped the dead Ollama branch (Ollama retired ecosystem-wide
2026-04-27 — its 900s timeout was the root of the score_images hang). Both
Reachy camera and carousel V2 Stage-8 now share the same cheap-VLM router
(Kimi K2.6 → OpenRouter free pool → Gemini Flash) defined in
``app.services.carousel_v2.cheap_vlm_router``.
"""

import base64
from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger(__name__)


class VisionService:
    """Process visual input from Reachy camera or uploaded images."""

    async def capture_and_describe(self, prompt: str = "Describe what you see.") -> Dict[str, Any]:
        """Capture image from Reachy camera and describe it using vision LLM."""
        try:
            from app.services.reachy_service import get_reachy_service
            reachy = get_reachy_service()
            image_bytes = await reachy.capture_image()

            if not image_bytes:
                return {"error": "Could not capture image from Reachy camera", "available": False}

            return await self.describe_image(image_bytes, prompt)
        except Exception as e:
            logger.error(f"Vision capture failed: {e}")
            return {"error": str(e), "available": False}

    async def describe_image(
        self,
        image_bytes: bytes,
        prompt: str = "Describe what you see.",
    ) -> Dict[str, Any]:
        """Describe an image using a multimodal LLM via the cheap-VLM router.

        Routes Kimi → OpenRouter free pool → Gemini Flash. Failure-soft:
        returns ``{"available": False, "error": ...}`` when every tier is
        exhausted instead of hanging on a dead local backend.
        """
        try:
            data_url = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Vision encode failed: {exc}")
            return {"error": f"encode_failed: {exc}", "available": False}

        try:
            from app.services.carousel_v2.cheap_vlm_router import verify_image
        except Exception as exc:  # noqa: BLE001
            return {"error": f"vlm_router_unavailable: {exc}", "available": False}

        # The router's prompt is character-verification-shaped (returns JSON);
        # for the Reachy free-form description path we wrap the user-supplied
        # prompt and accept whatever the model emits.
        try:
            result = await verify_image(
                data_url,
                character=prompt,        # router treats this as the subject line
                franchise=None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Vision describe failed: {exc}")
            return {"error": str(exc), "available": False}

        if not result.get("_available"):
            return {"error": result.get("error", "all_tiers_exhausted"), "available": False}

        # The router's JSON shape isn't a free-form description; surface the
        # ``character`` field as the description and keep the model id.
        return {
            "description": result.get("character") or "",
            "model": result.get("_model"),
            "tier": result.get("_tier"),
            "available": True,
            "raw": result,
        }

    async def detect_presence(self) -> Dict[str, Any]:
        """Check if a person is visible in the camera."""
        result = await self.capture_and_describe(
            "Is there a person visible in this image? Reply with only: YES or NO, then a brief description of what you see."
        )
        if result.get("description"):
            desc = result["description"].strip().upper()
            return {
                "person_detected": desc.startswith("YES"),
                "description": result["description"],
                "available": True,
            }
        return {"person_detected": False, "available": False, "error": result.get("error")}


_vision_service: Optional[VisionService] = None

def get_vision_service() -> VisionService:
    global _vision_service
    if _vision_service is None:
        _vision_service = VisionService()
    return _vision_service


async def describe_image_url(
    url: str,
    *,
    prompt: str = "Describe this image as JSON.",
    json_mode: bool = False,
) -> Dict[str, Any]:
    """Legacy thin shim — kept for any code still importing this helper.

    All vision routing now goes through ``carousel_v2.cheap_vlm_router``,
    so URL-based callers get the same Kimi → free pool → Gemini fallback
    chain as Stage-8.
    """
    try:
        from app.services.carousel_v2.cheap_vlm_router import verify_image
    except Exception as exc:  # noqa: BLE001
        return {"error": f"vlm_router_unavailable: {exc}", "available": False}

    try:
        result = await verify_image(url, character=prompt, franchise=None)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "available": False}

    if json_mode:
        # cheap_vlm_router already returns a dict; normalise the legacy
        # ``_model`` / ``_available`` fields.
        result.setdefault("_available", result.get("_available", True))
        return result

    return {
        "description": result.get("character") or "",
        "model": result.get("_model"),
        "available": result.get("_available", False),
        "raw": result,
    }
