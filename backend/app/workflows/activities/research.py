"""Researcher activity — fetches atomic facts from the tiered source ledger.

Phase 3 implementation: pulls from the existing
``character_research_sources`` (Fandom + Reddit + TV Tropes + IMDb +
Wikipedia + Comic Vine + SuperHero DB), tags each fragment with a trust
tier, persists to ``atomic_facts`` via ``atomic_facts_service.upsert``, and
returns the new fact ids on the workflow context.

Failure-soft: when the legacy research returns nothing, the activity still
succeeds with an empty list. The Designer + Skeptic downstream both refuse
to publish without ≥1 atomic fact, so emptiness is caught at the rubric
gate, not here.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from temporalio import activity

logger = structlog.get_logger(__name__)


# Map source kind from existing research_sources.py output → AtomicFact
# trust tier (carosel.txt §3 'Tiered source ledger').
_TIER_BY_SOURCE = {
    "fandom_wiki": 1,
    "wikipedia": 1,
    "wikidata": 1,
    "tmdb": 1,
    "comic_vine": 1,
    "superhero_db": 1,
    "imdb_trivia": 2,
    "imdb": 2,
    "tv_tropes": 3,
    "reddit": 3,
    "youtube": 3,
    "screen_rant": 4,
    "cbr": 4,
}

_SOURCE_KIND_BY_SOURCE = {
    "fandom_wiki": "fandom",
    "wikipedia": "wikipedia",
    "wikidata": "wikidata",
    "tmdb": "tmdb",
    "comic_vine": "comic_vine",
    "imdb_trivia": "imdb_graphql",
    "imdb": "imdb_graphql",
    "reddit": "reddit",
    "youtube": "youtube",
    "screen_rant": "news",
    "cbr": "news",
    "tv_tropes": "other",
    "superhero_db": "other",
}


@activity.defn
async def research(ctx: dict[str, Any]) -> dict[str, Any]:
    activity.heartbeat({"stage": "research", "generation_id": ctx["generation_id"]})

    # Lazy imports — keeps the workflow side import-cheap.
    from app.services.carousel_v2.atomic_facts_service import make_fact, upsert
    from app.models.carousel import TrustTier

    fact_ids: list[str] = []
    franchise = ctx.get("franchise")
    character = ctx["topic"]

    try:
        from app.services.character_research_sources import gather_research_fragments
    except Exception as exc:  # noqa: BLE001
        logger.warning("research_sources_unavailable", error=str(exc))
        ctx["atomic_fact_ids"] = []
        ctx["research_summary"] = ""
        ctx["status"] = "researched"
        return ctx

    try:
        fragments = await asyncio.wait_for(
            gather_research_fragments(character=character, franchise=franchise),
            timeout=120.0,
        )
    except asyncio.TimeoutError:
        logger.warning("research_timeout", character=character)
        fragments = []
    except Exception as exc:  # noqa: BLE001
        logger.warning("research_fetch_failed", character=character, error=str(exc))
        fragments = []

    for frag in fragments or []:
        source = (frag.get("source") or "other").lower()
        tier = _TIER_BY_SOURCE.get(source, 4)
        kind = _SOURCE_KIND_BY_SOURCE.get(source, "other")
        url = frag.get("url") or ""
        content = (frag.get("content") or frag.get("text") or "").strip()
        if not (url and content):
            continue
        # Treat each fragment as a single (subject, contains, object) row.
        # The LLM-driven decomposition into finer atomic claims happens in
        # the Designer; the ledger keeps the raw fragments as evidence.
        fact = make_fact(
            subject=character,
            predicate="contains",
            obj=content[:1500],
            source_kind=kind,
            source_url=url,
            source_quote=content[:500],
            trust_tier=TrustTier(tier),
            entity_type="character",
            franchise=franchise,
        )
        try:
            stored = await upsert(fact)
            fact_ids.append(stored.id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("fact_upsert_failed", error=str(exc))

    ctx["atomic_fact_ids"] = fact_ids
    ctx["research_summary"] = f"{len(fact_ids)} atomic facts ingested"
    ctx["status"] = "researched"
    logger.info("carousel_research_done", generation_id=ctx["generation_id"], facts=len(fact_ids))
    return ctx
