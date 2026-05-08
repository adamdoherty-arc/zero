"""Reddit image source — fan-curated HD scene captures via OAuth API.

Targets top-of-month/year on per-property subs. Handles ``is_gallery=True``
posts via ``gallery_data["items"]`` + ``media_metadata``. Uses the
PRAW-style script-app OAuth flow with client credentials.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import structlog

from app.infrastructure.config import get_settings
from app.services.image_sources.types import CandidateImage, ImageQuery

logger = structlog.get_logger(__name__)

OAUTH = "https://www.reddit.com/api/v1/access_token"
API = "https://oauth.reddit.com"

PROPERTY_SUBS: dict[str, list[str]] = {
    "marvel": ["Marvel", "MarvelStudios", "MCU", "comicbookart"],
    "mcu": ["MarvelStudios", "Marvel", "MCU", "marvelmemes"],
    "dc": ["DCcinematic", "DC_Cinematic", "DCComics", "comicbookart"],
    "dceu": ["DCcinematic", "DC_Cinematic", "Snyderverse"],
    "the_boys": ["TheBoys", "GenV"],
    "snyderverse": ["Snyderverse", "DC_Cinematic"],
    "stranger_things": ["StrangerThings"],
    "got": ["gameofthrones", "freefolk"],
    "hotd": ["HouseOfTheDragon"],
}

_TOKEN: tuple[str, float] | None = None


async def _token() -> str | None:
    global _TOKEN
    s = get_settings()
    if not (s.reddit_client_id and s.reddit_client_secret):
        return None
    if _TOKEN and _TOKEN[1] > time.time() + 30:
        return _TOKEN[0]
    auth = httpx.BasicAuth(s.reddit_client_id, s.reddit_client_secret)
    headers = {"User-Agent": s.reddit_user_agent}
    data = {"grant_type": "client_credentials"}
    async with httpx.AsyncClient(timeout=15.0) as c:
        try:
            r = await c.post(OAUTH, auth=auth, headers=headers, data=data)
            r.raise_for_status()
            payload = r.json()
            _TOKEN = (payload["access_token"], time.time() + int(payload.get("expires_in", 3600)))
            return _TOKEN[0]
        except Exception as exc:  # noqa: BLE001
            logger.warning("reddit_token_failed", error=str(exc))
            return None


def _resolve_image_urls(post: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    if post.get("is_gallery") and post.get("media_metadata"):
        items = (post.get("gallery_data") or {}).get("items", []) or []
        for it in items:
            mid = it.get("media_id")
            md = (post["media_metadata"] or {}).get(mid) or {}
            s = (md.get("s") or {}).get("u")
            if s:
                urls.append(s.replace("&amp;", "&"))
        return urls

    url = post.get("url_overridden_by_dest") or post.get("url")
    if url:
        # Strip query string before checking extension — Reddit preview URLs
        # carry ``?width=...&auto=webp`` after the .jpg/.png path.
        no_query = url.split("?")[0]
        if any(no_query.lower().endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp")):
            if "preview.redd.it" in no_query:
                no_query = no_query.replace("preview.redd.it", "i.redd.it")
            urls.append(no_query)
    return urls


async def fetch(query: ImageQuery, *, limit: int = 40) -> list[CandidateImage]:
    s = get_settings()
    token = await _token()
    if not token:
        return []

    franchise_key = (query.franchise or "").lower().replace(" ", "_")
    subs = PROPERTY_SUBS.get(franchise_key, ["movies", "television"])
    headers = {"Authorization": f"Bearer {token}", "User-Agent": s.reddit_user_agent}
    out: list[CandidateImage] = []
    async with httpx.AsyncClient(base_url=API, headers=headers, timeout=15.0) as c:
        for sub in subs:
            try:
                r = await c.get(
                    f"/r/{sub}/search",
                    params={
                        "q": query.character,
                        "restrict_sr": "true",
                        "sort": "top",
                        "t": "month",
                        "limit": min(25, limit - len(out)),
                    },
                )
                r.raise_for_status()
                listings = r.json().get("data", {}).get("children", []) or []
            except Exception as exc:  # noqa: BLE001
                logger.warning("reddit_search_failed", sub=sub, error=str(exc))
                continue
            for child in listings:
                post = child.get("data", {}) or {}
                if post.get("over_18"):
                    continue
                for url in _resolve_image_urls(post):
                    out.append(
                        CandidateImage(
                            source="reddit_praw",
                            source_url=url,
                            title=post.get("title"),
                            description=f"r/{sub} top-month",
                            license="Reddit user-submitted",
                            attribution=post.get("author"),
                            raw_metadata={"sub": sub, "score": post.get("score"), "id": post.get("id")},
                        )
                    )
                    if len(out) >= limit:
                        return out
            await asyncio.sleep(0.5)  # Reddit gentle pace
    return out
