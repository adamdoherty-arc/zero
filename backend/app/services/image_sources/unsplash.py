"""Unsplash — generic free image fallback for orphan characters."""

from __future__ import annotations

import httpx
import structlog

from app.infrastructure.config import get_settings
from app.services.image_sources.types import CandidateImage, ImageQuery

logger = structlog.get_logger(__name__)


async def fetch(query: ImageQuery, *, limit: int = 15) -> list[CandidateImage]:
    s = get_settings()
    if not s.unsplash_access_key:
        return []
    headers = {"Authorization": f"Client-ID {s.unsplash_access_key}"}
    params = {"query": query.character, "per_page": min(30, limit), "orientation": "portrait"}
    async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
        try:
            r = await client.get("https://api.unsplash.com/search/photos", params=params)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("unsplash_search_failed", error=str(exc))
            return []
    out: list[CandidateImage] = []
    for p in data.get("results", []) or []:
        src = (p.get("urls") or {}).get("full") or (p.get("urls") or {}).get("regular")
        if not src:
            continue
        out.append(
            CandidateImage(
                source="unsplash",
                source_url=src,
                width=p.get("width"),
                height=p.get("height"),
                description=p.get("alt_description") or p.get("description"),
                license="Unsplash free",
                attribution=(p.get("user") or {}).get("name"),
                raw_metadata={"id": p.get("id")},
            )
        )
        if len(out) >= limit:
            break
    return out
