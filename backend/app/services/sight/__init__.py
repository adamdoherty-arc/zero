"""
Sight — wearable-agnostic vision provider layer.

`SightProvider` is the single abstraction that Reachy's camera, a USB
webcam, and (later) Meta Ray-Ban glasses all satisfy. The rest of Zero
— vision VLM, ambient tick, voice loop — reads from
`registry.get_active_provider()` and doesn't care where the frame
came from.
"""

from .base import SightProvider, SightStatus
from .registry import SightRegistry, get_sight_registry

__all__ = [
    "SightProvider",
    "SightStatus",
    "SightRegistry",
    "get_sight_registry",
]
