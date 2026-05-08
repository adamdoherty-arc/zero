"""Comic Vine image source — canonical Marvel/DC art (covers, character bios).

Rate-limited to 200 req/hr/resource. Non-commercial license caveat —
treat outputs as transformative (commentary/criticism), small attribution
footer in render.
"""

from __future__ import annotations

import httpx
import structlog

from app.infrastructure.config import get_settings
from app.services.image_sources.types import CandidateImage, ImageQuery

logger = structlog.get_logger(__name__)

BASE = "https://comicvine.gamespot.com/api"


async def fetch(query: ImageQuery, *, limit: int = 25) -> list[CandidateImage]:
    s = get_settings()
    if not s.comicvine_api_key:
        return []

    headers = {"User-Agent": s.imdb_graphql_user_agent or "zero-carousel/1.0"}
    params = {
        "api_key": s.comicvine_api_key,
        "format": "json",
        "query": query.character,
        "resources": "character,issue,volume",
        "limit": limit,
    }
    out: list[CandidateImage] = []
    async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
        try:
            r = await client.get(f"{BASE}/search/", params=params)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("comicvine_search_failed", error=str(exc))
            return out
        for item in data.get("results", []) or []:
            image = item.get("image") or {}
            url = image.get("super_url") or image.get("original_url")
            if not url:
                continue
            out.append(
                CandidateImage(
                    source="comic_vine",
                    source_url=url,
                    title=item.get("name"),
                    description=item.get("deck") or "",
                    license="Comic Vine non-commercial",
                    attribution="Comic Vine",
                    raw_metadata={"resource_type": item.get("resource_type")},
                )
            )
            if len(out) >= limit:
                break
    return out
