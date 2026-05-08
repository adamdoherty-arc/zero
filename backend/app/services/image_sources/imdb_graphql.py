"""IMDb GraphQL — title + person primary images, plus trivia/quotes harvested
in Phase 3. The text outputs feed atomic_facts; the title-card thumbnails
feed image candidates.

No API key — courteous user agent + low rate is the bar.
"""

from __future__ import annotations

import httpx
import structlog

from app.infrastructure.config import get_settings
from app.services.image_sources.types import CandidateImage, ImageQuery

logger = structlog.get_logger(__name__)

GQL_URL = "https://api.graphql.imdb.com/"

_QUERY = """
query Title($id: ID!) {
  title(id: $id) {
    primaryImage { url width height caption { plainText } }
    images(first: 24, filter: { types: [POSTER, PRODUCTION_ART, EVENT, STILL_FRAME] }) {
      edges { node { url width height type caption { plainText } } }
    }
  }
}
"""


async def fetch(query: ImageQuery, *, limit: int = 24) -> list[CandidateImage]:
    s = get_settings()
    if not query.title_id or not query.title_id.startswith("tt"):
        return []

    headers = {
        "User-Agent": s.imdb_graphql_user_agent or "zero-carousel/1.0",
        "Content-Type": "application/json",
    }
    out: list[CandidateImage] = []
    async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
        try:
            r = await client.post(
                GQL_URL,
                json={"query": _QUERY, "variables": {"id": query.title_id}},
            )
            r.raise_for_status()
            data = r.json().get("data", {}).get("title") or {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("imdb_graphql_failed", id=query.title_id, error=str(exc))
            return out

        primary = data.get("primaryImage") or {}
        if primary.get("url"):
            out.append(
                CandidateImage(
                    source="imdb",
                    source_url=primary["url"],
                    width=primary.get("width"),
                    height=primary.get("height"),
                    description=(primary.get("caption") or {}).get("plainText"),
                    license="IMDb fair-use",
                    attribution="IMDb",
                    raw_metadata={"primary": True, "id": query.title_id},
                )
            )
        for edge in (data.get("images") or {}).get("edges", []) or []:
            node = edge.get("node") or {}
            if not node.get("url"):
                continue
            out.append(
                CandidateImage(
                    source="imdb",
                    source_url=node["url"],
                    width=node.get("width"),
                    height=node.get("height"),
                    description=(node.get("caption") or {}).get("plainText"),
                    license="IMDb fair-use",
                    attribution="IMDb",
                    raw_metadata={"type": node.get("type"), "id": query.title_id},
                )
            )
            if len(out) >= limit:
                break
    return out
