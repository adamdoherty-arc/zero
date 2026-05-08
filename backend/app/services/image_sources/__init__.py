"""Image source plugins for the carousel V2 fan-out fetcher.

Each module exposes::

    async def fetch(query: ImageQuery, *, limit: int) -> list[CandidateImage]

Plugins fail soft (return [] on error) so a single dead source never blocks
the whole curation step. ``ImageCuratorService`` runs them concurrently via
``aiometer`` with per-source rate-limit caps.
"""

from app.services.image_sources.types import CandidateImage, ImageQuery

__all__ = ["CandidateImage", "ImageQuery"]
