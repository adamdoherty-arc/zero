"""Fanart.tv image source — single biggest image-quality unlock per blueprint.

Returns ``characterart`` (pre-cut PNGs with alpha), ``clearart``, ``hdmovielogo``,
``movieart``. Drops directly onto colored carousel backgrounds with zero further
processing — the cinematic post-pass in Phase 5 then applies the LUT/grain/vignette.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from app.infrastructure.config import get_settings
from app.services.image_sources.types import CandidateImage, ImageQuery

logger = structlog.get_logger(__name__)

BASE = "https://webservice.fanart.tv/v3"


async def fetch(query: ImageQuery, *, limit: int = 30) -> list[CandidateImage]:
    s = get_settings()
    if not s.fanart_api_key:
        return []

    # Fanart.tv keys by TVDB / TMDB id. We accept both via query.title_id.
    if not query.title_id:
        return []

    out: list[CandidateImage] = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        for kind in ("tv", "movies"):
            url = f"{BASE}/{kind}/{query.title_id}"
            try:
                r = await client.get(url, params={"api_key": s.fanart_api_key})
                if r.status_code == 404:
                    continue
                r.raise_for_status()
                data = r.json()
            except Exception as exc:  # noqa: BLE001
                logger.warning("fanart_fetch_failed", kind=kind, id=query.title_id, error=str(exc))
                continue

            buckets = (
                "characterart", "clearart", "hdmovielogo",
                "movieart", "showbackground", "moviebackground",
            )
            for bucket in buckets:
                for entry in data.get(bucket, []) or []:
                    url_ = entry.get("url")
                    if not url_:
                        continue
                    out.append(
                        CandidateImage(
                            source="fanart",
                            source_url=url_,
                            description=f"fanart {bucket}",
                            license="Fanart.tv community",
                            attribution=entry.get("user_name") or "Fanart.tv",
                            raw_metadata={
                                "bucket": bucket,
                                "likes": entry.get("likes"),
                                "lang": entry.get("lang"),
                            },
                        )
                    )
                    if len(out) >= limit:
                        return out
            break  # first matching kind wins
    return out
