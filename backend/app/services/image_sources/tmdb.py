"""TMDB image source — primary metadata + stills.

Per carosel.txt §1: ``/movie/{id}/images``, ``/tv/{id}/images``,
``/tv/{id}/season/{n}/episode/{e}/images`` (per-episode ``stills[]``),
``/person/{id}/images``, ``append_to_response=images&include_image_language=en,null``.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx
import structlog

from app.infrastructure.config import get_settings
from app.services.image_sources.types import CandidateImage, ImageQuery

logger = structlog.get_logger(__name__)

BASE = "https://api.themoviedb.org/3"
IMG_BASE = "https://image.tmdb.org/t/p"


def _bearer() -> Optional[str]:
    s = get_settings()
    return s.tmdp_read_access_token or None


def _api_key() -> Optional[str]:
    s = get_settings()
    return s.tmdp_api_key or None


async def _client() -> httpx.AsyncClient:
    headers = {"Accept": "application/json"}
    if (token := _bearer()):
        headers["Authorization"] = f"Bearer {token}"
    return httpx.AsyncClient(base_url=BASE, headers=headers, timeout=15.0)


async def _search_title(client: httpx.AsyncClient, query: ImageQuery) -> tuple[str, str] | None:
    """Returns (kind, id) where kind is 'movie' or 'tv', or None.

    The voice-key form of franchise (``"the_boys"``) doesn't match TMDB's
    search index — TMDB knows it as ``"The Boys"``. Normalise underscores
    to spaces before querying. Falls back to the character name if the
    franchise search comes back empty.
    """
    candidates: list[str] = []
    if query.franchise:
        candidates.append(query.franchise.replace("_", " "))
    if query.character and query.character not in candidates:
        candidates.append(query.character)

    if not _bearer() and (k := _api_key()):
        api_key_param = {"api_key": k}
    else:
        api_key_param = {}

    for term in candidates:
        try:
            r = await client.get("/search/multi", params={"query": term, **api_key_param})
            r.raise_for_status()
            for item in r.json().get("results", []):
                if item.get("media_type") in {"movie", "tv"}:
                    return item["media_type"], str(item["id"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("tmdb_search_failed", term=term, error=str(exc))
    return None


async def fetch(query: ImageQuery, *, limit: int = 50) -> list[CandidateImage]:
    if not (_bearer() or _api_key()):
        return []

    out: list[CandidateImage] = []
    async with await _client() as client:
        hit = await _search_title(client, query)
        if not hit:
            return out
        kind, tmdb_id = hit
        try:
            r = await client.get(
                f"/{kind}/{tmdb_id}/images",
                params={"include_image_language": "en,null"},
            )
            r.raise_for_status()
            data = r.json()
            for bucket in ("backdrops", "stills", "posters"):
                for img in data.get(bucket, []):
                    if not img.get("file_path"):
                        continue
                    full = f"{IMG_BASE}/original{img['file_path']}"
                    out.append(
                        CandidateImage(
                            source="tmdb",
                            source_url=full,
                            width=img.get("width"),
                            height=img.get("height"),
                            description=f"{kind}/{tmdb_id} {bucket}",
                            license="TMDB courtesy",
                            attribution="The Movie Database (TMDB)",
                            raw_metadata={"tmdb_id": tmdb_id, "kind": kind, "bucket": bucket},
                        )
                    )
                    if len(out) >= limit:
                        return out
        except Exception as exc:  # noqa: BLE001
            logger.warning("tmdb_images_failed", tmdb_id=tmdb_id, error=str(exc))
    return out
