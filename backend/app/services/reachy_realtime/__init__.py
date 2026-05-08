"""
Reachy realtime voice chat — port of pollen-robotics/reachy_mini_conversation_app.

Provides bidirectional audio conversations with OpenAI Realtime (gpt-realtime)
and Gemini Live (gemini-*-live-preview) backends, with tool-calling wired to
Zero's existing reachy_service so the robot moves, dances, and plays emotions
while it talks.

Adapted from
https://github.com/pollen-robotics/reachy_mini_conversation_app (Apache 2.0).
Upstream uses fastrtc + Gradio; this port swaps those for a raw WebSocket
bridge so the browser talks directly to the Zero FastAPI backend and the
existing reachy_service/daemon stack handles motion.
"""

from app.services.reachy_realtime.common import (
    BACKEND_OPENAI,
    BACKEND_GEMINI,
    OPENAI_AVAILABLE_VOICES,
    GEMINI_AVAILABLE_VOICES,
    DEFAULT_MODEL_BY_BACKEND,
    DEFAULT_VOICE_BY_BACKEND,
    ToolDependencies,
    MotionDispatcher,
)

__all__ = [
    "BACKEND_OPENAI",
    "BACKEND_GEMINI",
    "OPENAI_AVAILABLE_VOICES",
    "GEMINI_AVAILABLE_VOICES",
    "DEFAULT_MODEL_BY_BACKEND",
    "DEFAULT_VOICE_BY_BACKEND",
    "ToolDependencies",
    "MotionDispatcher",
]
