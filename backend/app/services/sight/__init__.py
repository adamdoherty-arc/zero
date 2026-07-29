"""
Sight — wearable-agnostic vision provider layer.

`SightProvider` is the single abstraction that a phone camera and
Meta Ray-Ban glasses both satisfy. The rest of Zero — vision VLM,
ambient tick — reads from `registry.get_active_provider()` and
doesn't care where the frame came from.
"""

from .base import SightProvider, SightStatus
from .registry import SightRegistry, get_sight_registry

__all__ = [
    "SightProvider",
    "SightStatus",
    "SightRegistry",
    "get_sight_registry",
]
