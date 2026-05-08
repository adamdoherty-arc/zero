"""
Entity Research Service — Phase 036 (24/7 Employee).

Drives deeper, typed research for characters, TV shows, and movies. Picks the
entities most in need of depth (lowest research_depth_score) and kicks off
DeepResearchService runs with queries tailored to the entity type. When a
deep-research report completes, its markdown/sections are merged into the
character's research_data and chunked into CharacterLoreChunkModel so the
carousel synthesis pipeline can RAG over them.

This is the "researches each character, tv, and movie for adequate information"
workstream of the 24/7 Employee plan.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError

from app.db.models import (
    CharacterLoreChunkModel,
    CharacterModel,
    DeepResearchReportModel,
)
from app.infrastructure.database import get_session
from app.models.agent_company import DeepResearchRequest
from app.services.deep_research_service import get_deep_research_service

logger = structlog.get_logger(__name__)


_PROFILE_VERSION = "v1"

# Perspectives per entity type (drives the DR pipeline).
_PERSPECTIVES = {
    "character": ["biography", "powers_and_abilities", "relationships", "fan_theories", "behind_the_scenes"],
    "tv": ["synopsis", "cast_and_crew", "production", "reception", "iconic_episodes"],
    "movie": ["synopsis", "cast_and_crew", "production", "box_office", "cultural_impact"],
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _entity_type_of(char: CharacterModel) -> str:
    """Infer entity_type from universe / franchise hints stored on the character.
    Falls back to 'character' which is the default profile."""
    uni = (char.universe or "").lower()
    franchise = (char.franchise or "").lower()
    if "tv" in uni or "show" in franchise or "series" in franchise:
        return "tv"
    if "movie" in uni or "film" in franchise:
        return "movie"
    return "character"


def _research_query(char: CharacterModel, entity_type: str) -> str:
    who = char.name
    if char.franchise:
        who = f"{who} ({char.franchise})"
    elif char.universe and char.universe.lower() != "other":
        who = f"{who} ({char.universe})"
    if entity_type == "tv":
        return f"Deep research on the TV show '{who}': synopsis, cast, showrunner, critical reception, iconic episodes, behind-the-scenes trivia."
    if entity_type == "movie":
        return f"Deep research on the movie '{who}': synopsis, cast, director, production history, box office, cultural impact, surprising trivia."
    return (
        f"Deep research on the character '{who}': biography, powers and abilities, "
        f"relationships, critical arcs, fan theories, behind-the-scenes, notable quotes."
    )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class EntityResearchService:
    async def deepen_lowest_depth(self, batch_size: int = 3) -> Dict[str, Any]:
        """Fire deep-research runs for the N entities with lowest depth score.

        Strategy:
          1. Pick active characters with research_depth_score < 0.6 that are not
             already researching AND haven't had a DR fired in the last 24h.
          2. For each, start a DeepResearchService run with entity-appropriate
             perspectives. Store the DR report id on the character under
             research_data['pending_deep_research_id'] and stamp last_researched.
          3. Separately, ingest any DR reports that have already completed into
             the character's research_data + lore chunks.
        """
        ingested = await self._ingest_completed_reports(batch_size=10)
        scanned = 0
        launched = 0
        skipped = 0
        errors = 0
        now = _now()

        async with get_session() as session:
            q = (
                select(CharacterModel)
                .where(
                    CharacterModel.status == "active",
                    CharacterModel.autonomous_disabled.is_(False),
                    or_(
                        CharacterModel.research_depth_score < 0.6,
                        CharacterModel.research_depth_score.is_(None),
                    ),
                )
                .order_by(CharacterModel.research_depth_score.asc().nullsfirst())
                .limit(batch_size * 3)  # over-fetch since we filter below
            )
            candidates = (await session.execute(q)).scalars().all()

        for char in candidates:
            if launched >= batch_size:
                break
            scanned += 1
            # Skip if we already have a pending DR fired recently (<24h)
            research_data = char.research_data or {}
            pending_id = research_data.get("pending_deep_research_id")
            fired_at = research_data.get("deep_research_fired_at")
            if pending_id and fired_at:
                try:
                    ts = datetime.fromisoformat(fired_at)
                    if (now - ts).total_seconds() < 86400:
                        skipped += 1
                        continue
                except (ValueError, TypeError):
                    pass

            entity_type = _entity_type_of(char)
            query = _research_query(char, entity_type)

            try:
                report = await get_deep_research_service().start_research(
                    DeepResearchRequest(
                        query=query,
                        perspectives=_PERSPECTIVES.get(entity_type, _PERSPECTIVES["character"]),
                        max_cost_usd=0.50,
                    )
                )
                async with get_session() as session:
                    fresh = await session.get(CharacterModel, char.id)
                    if fresh:
                        rd = dict(fresh.research_data or {})
                        rd["pending_deep_research_id"] = report.id
                        rd["deep_research_fired_at"] = now.isoformat()
                        rd.setdefault("deep_research_history", []).append({
                            "report_id": report.id,
                            "entity_type": entity_type,
                            "fired_at": now.isoformat(),
                        })
                        fresh.research_data = rd
                        fresh.profile_version = _PROFILE_VERSION
                        await session.flush()
                launched += 1
            except (SQLAlchemyError, ValueError, RuntimeError, AttributeError) as e:
                errors += 1
                logger.warning("entity_research_fire_failed", character_id=char.id, error=str(e))

        stats = {
            "scanned": scanned,
            "launched": launched,
            "skipped_recent": skipped,
            "ingested": ingested,
            "errors": errors,
        }
        if launched or ingested:
            logger.info("entity_research_deepen_done", **stats)
        return stats

    async def _ingest_completed_reports(self, batch_size: int = 10) -> int:
        """Find completed DeepResearchReports linked to a character (via
        pending_deep_research_id) and merge their content into the character.
        Also chunks the report into CharacterLoreChunkModel rows for RAG."""
        ingested = 0
        async with get_session() as session:
            q = (
                select(CharacterModel)
                .where(
                    CharacterModel.research_data.has_key("pending_deep_research_id")  # type: ignore[attr-defined]
                )
                .limit(batch_size)
            )
            try:
                chars = (await session.execute(q)).scalars().all()
            except SQLAlchemyError:
                chars = []

        for char in chars:
            rd = dict(char.research_data or {})
            report_id = rd.get("pending_deep_research_id")
            if not report_id:
                continue
            async with get_session() as session:
                report = await session.get(DeepResearchReportModel, report_id)
            if not report or report.status != "completed":
                continue
            try:
                await self._merge_report_into_character(char.id, report)
                ingested += 1
            except (SQLAlchemyError, ValueError, KeyError, TypeError) as e:
                logger.warning(
                    "entity_research_ingest_failed",
                    character_id=char.id,
                    report_id=report_id,
                    error=str(e),
                )
        return ingested

    async def _merge_report_into_character(
        self, character_id: str, report: DeepResearchReportModel
    ) -> None:
        """Write the report's markdown into research_data and chunk it into
        character_lore_chunks. Bump research_depth_score."""
        async with get_session() as session:
            char = await session.get(CharacterModel, character_id)
            if not char:
                return

            rd = dict(char.research_data or {})
            rd.pop("pending_deep_research_id", None)
            rd["latest_deep_research_summary"] = report.executive_summary
            rd["latest_deep_research_report_id"] = report.id
            rd["latest_deep_research_completed_at"] = _now().isoformat()
            if report.sections:
                rd.setdefault("sections", {}).update(report.sections)

            sources = list(char.research_sources or [])
            for src in (report.sources or []):
                if isinstance(src, dict) and src not in sources:
                    sources.append(src)
            char.research_sources = sources
            char.research_data = rd
            char.last_researched = _now()
            # Modest depth bump — capped at 1.0
            char.research_depth_score = min(1.0, (char.research_depth_score or 0.0) + 0.25)
            char.research_status = "completed"

            # Chunk the markdown into lore chunks for RAG
            if report.report_markdown:
                chunks = _chunk_text(report.report_markdown, target=900)
                for i, text in enumerate(chunks):
                    chunk_id = "lc-" + hashlib.sha256(
                        f"{character_id}:{report.id}:{i}".encode()
                    ).hexdigest()[:32]
                    session.add(CharacterLoreChunkModel(
                        id=chunk_id,
                        character_id=character_id,
                        source=f"deep_research:{report.id}",
                        source_license="derivative",
                        text=text,
                        chunk_index=i,
                        chunk_metadata={"report_id": report.id},
                    ))
            await session.flush()


def _chunk_text(text: str, target: int = 900) -> List[str]:
    """Split markdown into ~target-char chunks on paragraph boundaries."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    out: List[str] = []
    buf: List[str] = []
    length = 0
    for p in paragraphs:
        if length + len(p) > target and buf:
            out.append("\n\n".join(buf))
            buf, length = [], 0
        buf.append(p)
        length += len(p)
    if buf:
        out.append("\n\n".join(buf))
    return out


@lru_cache()
def get_entity_research_service() -> EntityResearchService:
    return EntityResearchService()
