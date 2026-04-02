"""
Vision Service — Process images from Reachy camera via multimodal LLM.

Capabilities:
- Describe what the camera sees
- Detect user presence
- Answer visual questions ("what's on my desk?")
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
            # Capture from Reachy
            from app.services.reachy_service import get_reachy_service
            reachy = get_reachy_service()
            image_bytes = await reachy.capture_image()

            if not image_bytes:
                return {"error": "Could not capture image from Reachy camera", "available": False}

            return await self.describe_image(image_bytes, prompt)
        except Exception as e:
            logger.error(f"Vision capture failed: {e}")
            return {"error": str(e), "available": False}

    async def describe_image(self, image_bytes: bytes, prompt: str = "Describe what you see.") -> Dict[str, Any]:
        """Describe an image using a multimodal LLM."""
        try:
            b64_image = base64.b64encode(image_bytes).decode("utf-8")

            # Try Ollama with a vision model first
            try:
                from app.infrastructure.ollama_client import get_ollama_client
                client = get_ollama_client()
                response = await client.chat(
                    messages=[{
                        "role": "user",
                        "content": prompt,
                        "images": [b64_image],
                    }],
                    model="llava",  # or moondream, llava-phi3
                    task_type="vision",
                    temperature=0.3,
                )
                return {
                    "description": response,
                    "model": "ollama/llava",
                    "available": True,
                }
            except Exception as ollama_err:
                logger.debug(f"Ollama vision failed, trying Gemini: {ollama_err}")

            # Fallback to Gemini vision
            try:
                import httpx
                import os
                api_key = os.getenv("GEMINI_API_KEY")
                if not api_key:
                    return {"error": "No vision LLM available (Ollama vision failed, no Gemini key)", "available": False}

                async with httpx.AsyncClient(timeout=30) as http:
                    resp = await http.post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}",
                        json={
                            "contents": [{
                                "parts": [
                                    {"text": prompt},
                                    {"inline_data": {"mime_type": "image/jpeg", "data": b64_image}},
                                ]
                            }]
                        },
                    )
                    data = resp.json()
                    text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    return {"description": text, "model": "gemini-2.0-flash", "available": True}
            except Exception as gemini_err:
                return {"error": f"All vision models failed: {gemini_err}", "available": False}

        except Exception as e:
            logger.error(f"Vision describe failed: {e}")
            return {"error": str(e), "available": False}

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
