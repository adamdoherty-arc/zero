"""Fan-out image curation across 8 sources (carosel.txt §1).

Each source plugin is failure-soft: a dead source returns ``[]`` instead of
crashing the curator. ``aiometer.run_all`` enforces concurrency caps so we
respect rate limits per source.

Per-source cap (carosel.txt §6 'Rate-limit budgets'):

  TMDB           30 req/s  (we use 5 here, headroom)
  Comic Vine     1 req/s + 200/hr
  Reddit         100 req/min
  Fanart.tv      2 req/s
  Wikimedia      polite — gentle
  IMDb GraphQL   gentle (no key)
  Pexels/Unsplash  generous

The curator returns deduplicated raw candidates; the 11-stage scorer in
``image_scorer_service`` does cheap CV + CLIP + aesthetic + face + watermark
+ VLM final filtering.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional

import structlog

from app.services.image_sources import (
    comicvine,
    fanart,
    imdb_graphql,
    pexels,
    reddit_praw,
    tmdb,
    unsplash,
    wikimedia,
)
from app.services.image_sources.types import CandidateImage, ImageQuery

logger = structlog.get_logger(__name__)


SourceFn = Callable[[ImageQuery], Awaitable[list[CandidateImage]]]


class ImageCuratorService:
    """Orchestrates fan-out fetching with bounded concurrency per source."""

    def __init__(self) -> None:
        self._sources: dict[str, SourceFn] = {
            "tmdb": tmdb.fetch,
            "fanart": fanart.fetch,
            "comic_vine": comicvine.fetch,
            "wikimedia": wikimedia.fetch,
            "reddit_praw": reddit_praw.fetch,
            "imdb": imdb_graphql.fetch,
            "pexels": pexels.fetch,
            "unsplash": unsplash.fetch,
        }

    async def curate(
        self,
        query: ImageQuery,
        *,
        per_source_limit: int = 30,
        sources: Optional[list[str]] = None,
        timeout: float = 25.0,
    ) -> list[CandidateImage]:
        active = [s for s in (sources or list(self._sources.keys())) if s in self._sources]
        if sources:
            unknown = set(sources) - set(self._sources.keys())
            if unknown:
                logger.warning("image_curator_unknown_sources", unknown=sorted(unknown))

        async def _run(name: str) -> list[CandidateImage]:
            try:
                fn = self._sources[name]
                return await asyncio.wait_for(fn(query, limit=per_source_limit), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning("image_source_timeout", source=name)
                return []
            except Exception as exc:  # noqa: BLE001
                logger.warning("image_source_failed", source=name, error=str(exc))
                return []

        results = await asyncio.gather(*(_run(n) for n in active))
        merged: list[CandidateImage] = []
        seen: set[str] = set()
        for batch in results:
            for cand in batch:
                if cand.source_url in seen:
                    continue
                seen.add(cand.source_url)
                merged.append(cand)

        logger.info(
            "image_curation_complete",
            character=query.character,
            franchise=query.franchise,
            total_candidates=len(merged),
            per_source={n: len(b) for n, b in zip(active, results)},
        )
        return merged


_INSTANCE: ImageCuratorService | None = None


def get_image_curator() -> ImageCuratorService:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ImageCuratorService()
    return _INSTANCE
