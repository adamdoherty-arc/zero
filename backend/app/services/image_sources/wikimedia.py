"""Wikimedia Commons image source.

Uses ``Special:FilePath`` for direct file access and the MediaWiki API for
license-tagged search. Only candidates with a permissive ``LicenseShortName``
(CC-BY, CC-BY-SA, public domain) flow through.
"""

from __future__ import annotations

import httpx
import structlog

from app.services.image_sources.types import CandidateImage, ImageQuery

logger = structlog.get_logger(__name__)

API = "https://commons.wikimedia.org/w/api.php"
ALLOWED_LICENSES = (
    "cc-by", "cc-by-sa", "cc-zero", "cc0",
    "cc by", "cc by-sa", "cc by 4.0", "cc by-sa 4.0",
    "public domain", "pd-",
)


def _license_ok(short: str | None) -> bool:
    if not short:
        return False
    s = short.strip().lower()
    if s == "pd":
        return True
    return s.startswith(ALLOWED_LICENSES)


async def fetch(query: ImageQuery, *, limit: int = 30) -> list[CandidateImage]:
    out: list[CandidateImage] = []
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"filetype:bitmap {query.character}",
        "gsrlimit": limit,
        "gsrnamespace": 6,  # File namespace
        "prop": "imageinfo",
        "iiprop": "url|size|extmetadata",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            r = await client.get(API, params=params)
            r.raise_for_status()
            pages = r.json().get("query", {}).get("pages", {}) or {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("wikimedia_search_failed", error=str(exc))
            return out
        for page in pages.values():
            info = (page.get("imageinfo") or [{}])[0]
            url = info.get("url")
            meta = info.get("extmetadata") or {}
            license_short = (meta.get("LicenseShortName") or {}).get("value")
            if not url or not _license_ok(license_short):
                continue
            out.append(
                CandidateImage(
                    source="wikimedia",
                    source_url=url,
                    title=page.get("title"),
                    width=info.get("width"),
                    height=info.get("height"),
                    license=license_short,
                    attribution=(meta.get("Artist") or {}).get("value"),
                    raw_metadata={"pageid": page.get("pageid")},
                )
            )
            if len(out) >= limit:
                break
    return out
