"""
Reachy Mini robot integration service.

REST client for the Reachy Mini daemon, providing head movement,
antenna control, emotion playback, TTS, and camera capture.
"""

import os
from typing import Optional
import structlog
import httpx

from app.services.tts_service import get_tts_service

logger = structlog.get_logger()

# Default Reachy Mini daemon URL
DEFAULT_REACHY_URL = "http://localhost:8000"


class ReachyService:
    """Async REST client for Reachy Mini robot daemon."""

    _instance: Optional["ReachyService"] = None

    def __init__(self):
        self._base_url = os.getenv("REACHY_API_URL", DEFAULT_REACHY_URL).rstrip("/")
        self._api_prefix = f"{self._base_url}/api/v1"
        self._client: Optional[httpx.AsyncClient] = None

    @classmethod
    def get_instance(cls) -> "ReachyService":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def is_connected(self) -> bool:
        """Check if Reachy Mini daemon is running and reachable."""
        try:
            client = self._get_client()
            resp = await client.get(f"{self._api_prefix}/status")
            return resp.status_code == 200
        except Exception as e:
            logger.debug("reachy_not_connected", error=str(e))
            return False

    async def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        """
        Make a request to the Reachy daemon with graceful error handling.

        Returns dict with response data or error status.
        """
        url = f"{self._api_prefix}{endpoint}"
        try:
            client = self._get_client()
            resp = await client.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except httpx.ConnectError:
            logger.warning("reachy_connection_failed", url=url)
            return {"error": "Robot not connected", "connected": False}
        except httpx.HTTPStatusError as e:
            logger.warning("reachy_request_failed", url=url, status=e.response.status_code)
            return {"error": f"Request failed: {e.response.status_code}", "connected": True}
        except Exception as e:
            logger.error("reachy_request_error", url=url, error=str(e))
            return {"error": str(e), "connected": False}

    async def move_head(
        self,
        roll: float = 0.0,
        pitch: float = 0.0,
        yaw: float = 0.0,
        duration: float = 1.0,
    ) -> dict:
        """
        Move the robot's head to specified orientation.

        Args:
            roll: Roll angle in degrees
            pitch: Pitch angle in degrees
            yaw: Yaw angle in degrees
            duration: Movement duration in seconds
        """
        return await self._request("POST", "/head/move", json={
            "roll": roll,
            "pitch": pitch,
            "yaw": yaw,
            "duration": duration,
        })

    async def look_at(
        self,
        x: float,
        y: float,
        z: float,
        duration: float = 1.0,
    ) -> dict:
        """
        Make the robot look at a point in 3D space.

        Args:
            x, y, z: Target coordinates in meters
            duration: Movement duration in seconds
        """
        return await self._request("POST", "/head/look_at", json={
            "x": x,
            "y": y,
            "z": z,
            "duration": duration,
        })

    async def set_antennas(
        self,
        left_angle: float = 0.0,
        right_angle: float = 0.0,
        duration: float = 0.5,
    ) -> dict:
        """
        Set antenna positions.

        Args:
            left_angle: Left antenna angle in degrees
            right_angle: Right antenna angle in degrees
            duration: Movement duration in seconds
        """
        return await self._request("POST", "/antennas/set", json={
            "left_angle": left_angle,
            "right_angle": right_angle,
            "duration": duration,
        })

    async def play_emotion(self, emotion: str) -> dict:
        """
        Play an emotion animation.

        Args:
            emotion: Emotion name (happy, sad, curious, surprised, angry, thinking)
        """
        return await self._request("POST", "/emotions/play", json={
            "emotion": emotion,
        })

    async def say(self, text: str) -> dict:
        """
        Speak text using TTS service and robot speaker.

        Synthesizes audio via TTSService, then sends to robot for playback.

        Args:
            text: Text to speak
        """
        try:
            tts = get_tts_service()
            audio_bytes = await tts.synthesize(text)

            # Send audio to robot for playback
            result = await self._request("POST", "/audio/play", content=audio_bytes, headers={
                "Content-Type": "audio/wav",
            })

            return {
                "text": text,
                "audio_size": len(audio_bytes),
                "playback": result,
            }
        except RuntimeError as e:
            logger.warning("reachy_say_failed", error=str(e))
            return {"error": str(e), "text": text}

    async def capture_image(self) -> bytes:
        """
        Capture an image from the robot's camera.

        Returns:
            JPEG image bytes
        """
        url = f"{self._api_prefix}/camera/capture"
        try:
            client = self._get_client()
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            logger.warning("reachy_camera_failed", error=str(e))
            return b""

    async def get_audio_direction(self) -> dict:
        """
        Get direction of arrival from robot microphones.

        Returns:
            Dict with angle and confidence of detected audio source
        """
        return await self._request("GET", "/audio/direction")

    def get_status_info(self) -> dict:
        """Get service configuration info (does not ping robot)."""
        return {
            "base_url": self._base_url,
            "api_prefix": self._api_prefix,
        }


def get_reachy_service() -> ReachyService:
    """Get singleton ReachyService instance."""
    return ReachyService.get_instance()
