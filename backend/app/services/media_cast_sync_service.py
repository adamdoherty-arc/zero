"""
TMDB cast sync service — populates ``character_media_titles`` from TMDB.

For each existing ``MediaTitleModel`` with a ``tmdb_id``, fetches the cast
list from TMDB and:
  1. Matches each cast row's ``character`` name to an existing
     ``CharacterModel`` (exact -> rapidfuzz token-set ratio >= 90).
  2. For top-billed orphans (TMDB ``order <= 5``), auto-creates a stub
     ``CharacterModel`` with ``status="pending"`` so review is explicit.
  3. Idempotently upserts a ``CharacterMediaTitleModel`` row.

Cameo pollution guard: only top 15 by billing order are considered, and
auto-create is gated on top-5 billing — "Asgardian Soldier #3" is skipped
unless a manual character match exists.

All matching is franchise/universe-scoped to prevent cross-franchise
false positives ("John" in two unrelated shows).
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import aiohttp
import structlog
from sqlalchemy import select

from app.db.models import (
    CharacterMediaTitleModel,
    CharacterModel,
    MediaTitleModel,
)
from app.infrastructure.config import get_settings
from app.infrastructure.database import get_session
from app.services.character_content_utils import generate_id

logger = structlog.get_logger()


_TMDB_BASE = "https://api.themoviedb.org/3"
_AUTO_CREATE_TOP_N = 5
_DEFAULT_TOP_N = 15


def _role_type_from_order(order: int, total: int) -> str:
    """Bucket TMDB cast.order into our role_type enum."""
    if order <= 2:
        return "lead"
    if order <= 5:
        return "supporting"
    if order <= 10:
        return "recurring"
    if order <= total // 2 + 5:
        return "guest"
    return "cameo"


def _fuzzy_ratio(a: str, b: str) -> int:
    """Token-set ratio 0-100. Falls back to difflib if rapidfuzz isn't present."""
    a_n = (a or "").strip().lower()
    b_n = (b or "").strip().lower()
    if not a_n or not b_n:
        return 0
    try:
        from rapidfuzz import fuzz  # type: ignore
        return int(fuzz.token_set_ratio(a_n, b_n))
    except ImportError:
        from difflib import SequenceMatcher
        return int(SequenceMatcher(None, a_n, b_n).ratio() * 100)


class MediaCastSyncService:
    """Pulls TMDB cast credits into ``character_media_titles``."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._tmdb_token = (
            getattr(self._settings, "tmdp_read_access_token", None)
            or getattr(self._settings, "TMDB_READ_ACCESS_TOKEN", None)
        )
        self._tmdb_key = (
            getattr(self._settings, "tmdp_api_key", None)
            or getattr(self._settings, "TMDB_API_KEY", None)
            or getattr(self._settings, "ZERO_TMDB_API_KEY", None)
        )

    @property
    def is_configured(self) -> bool:
        return bool(self._tmdb_token or self._tmdb_key)

    async def sync_cast_for_title(
        self,
        media_title_id: str,
        *,
        top_n: int = _DEFAULT_TOP_N,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Fetch TMDB cast for a title and upsert character_media_titles rows."""
        if not self.is_configured:
            return {
                "media_title_id": media_title_id,
                "error": "tmdb_not_configured",
            }

        async with get_session() as session:
            title = await session.get(MediaTitleModel, media_title_id)
            if not title:
                return {"media_title_id": media_title_id, "error": "not_found"}
            if not title.tmdb_id:
                return {
                    "media_title_id": media_title_id,
                    "title": title.title,
                    "error": "missing_tmdb_id",
                }
            tmdb_id = int(title.tmdb_id)
            media_type = title.media_type
            universe = title.universe
            franchise = title.franchise
            title_name = title.title

        try:
            cast = await self._fetch_cast(tmdb_id, media_type)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "cast_sync_fetch_failed",
                media_title_id=media_title_id, error=str(e)[:200],
            )
            return {"media_title_id": media_title_id, "error": "tmdb_fetch_failed"}

        # TMDB returns ``order`` per cast row for movies; aggregate_credits for
        # TV uses ``order`` too but it's the show-level billing order.
        cast = sorted(cast, key=lambda c: c.get("order", 9999))[:top_n]
        total = len(cast)

        matched = 0
        created_stubs = 0
        skipped_cameos = 0
        existing_links = 0
        upserts: List[Dict[str, Any]] = []

        for entry in cast:
            cast_character = (entry.get("character") or "").strip()
            actor_name = (entry.get("name") or "").strip()
            order = int(entry.get("order", 999))
            seasons = []
            if media_type == "tv_show":
                # aggregate_credits returns "total_episode_count" and per-role data.
                # Fall back to roles -> credit_id grouping for season hints.
                roles = entry.get("roles") or []
                for r in roles:
                    s = r.get("season_number")
                    if s is not None and s not in seasons:
                        seasons.append(int(s))

            if not cast_character:
                continue

            char_id = await self._match_character(
                cast_character, universe=universe, franchise=franchise,
            )

            if not char_id:
                if order < _AUTO_CREATE_TOP_N:
                    # Top-billed orphan — auto-create stub.
                    if dry_run:
                        char_id = "DRY_RUN"
                    else:
                        char_id = await self._create_stub_character(
                            name=cast_character,
                            universe=universe,
                            franchise=franchise,
                            source_title=title_name,
                            actor_name=actor_name,
                        )
                    created_stubs += 1
                else:
                    skipped_cameos += 1
                    continue

            role_type = _role_type_from_order(order, total)

            if dry_run:
                upserts.append({
                    "character": cast_character,
                    "actor": actor_name,
                    "role_type": role_type,
                    "order": order,
                    "matched_character_id": char_id,
                    "is_new_stub": char_id == "DRY_RUN",
                })
                matched += 1
                continue

            inserted = await self._upsert_link(
                character_id=char_id,
                media_title_id=media_title_id,
                role_name=cast_character,
                role_type=role_type,
                actor_name=actor_name,
                seasons_appeared=seasons,
            )
            if inserted:
                matched += 1
                upserts.append({
                    "character": cast_character,
                    "actor": actor_name,
                    "role_type": role_type,
                    "order": order,
                    "matched_character_id": char_id,
                })
            else:
                existing_links += 1

        logger.info(
            "cast_sync_complete",
            media_title_id=media_title_id,
            title=title_name,
            cast_size=total,
            matched=matched,
            created_stubs=created_stubs,
            skipped_cameos=skipped_cameos,
            existing_links=existing_links,
            dry_run=dry_run,
        )

        return {
            "media_title_id": media_title_id,
            "title": title_name,
            "cast_size": total,
            "matched": matched,
            "created_stubs": created_stubs,
            "skipped_cameos": skipped_cameos,
            "existing_links": existing_links,
            "dry_run": dry_run,
            "upserts": upserts,
        }

    async def sync_all_cast(
        self,
        *,
        universe: Optional[str] = None,
        media_type: Optional[str] = None,
        limit: Optional[int] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Iterate every media title and sync its cast."""
        async with get_session() as session:
            stmt = select(MediaTitleModel.id, MediaTitleModel.title) \
                .where(MediaTitleModel.tmdb_id.isnot(None))
            if universe:
                stmt = stmt.where(MediaTitleModel.universe == universe)
            if media_type:
                stmt = stmt.where(MediaTitleModel.media_type == media_type)
            stmt = stmt.order_by(MediaTitleModel.title.asc())
            if limit:
                stmt = stmt.limit(limit)
            titles = (await session.execute(stmt)).all()

        results: List[Dict[str, Any]] = []
        for tid, _ in titles:
            try:
                result = await self.sync_cast_for_title(
                    tid, dry_run=dry_run,
                )
                results.append(result)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "cast_sync_per_title_failed",
                    media_title_id=tid, error=str(e)[:200],
                )
                results.append({"media_title_id": tid, "error": str(e)[:200]})

        return {
            "titles_processed": len(results),
            "total_matched": sum(r.get("matched", 0) for r in results),
            "total_created_stubs": sum(r.get("created_stubs", 0) for r in results),
            "total_skipped_cameos": sum(r.get("skipped_cameos", 0) for r in results),
            "total_existing_links": sum(r.get("existing_links", 0) for r in results),
            "dry_run": dry_run,
            "details": results,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_cast(self, tmdb_id: int, media_type: str) -> List[Dict[str, Any]]:
        """Fetch cast list from TMDB.

        TV uses ``aggregate_credits`` (all-season cast).
        Movies use ``credits``.
        """
        if media_type == "tv_show":
            endpoint = f"/tv/{tmdb_id}/aggregate_credits"
        else:
            endpoint = f"/movie/{tmdb_id}/credits"

        url = f"{_TMDB_BASE}{endpoint}"
        headers = {"Accept": "application/json"}
        params: Dict[str, Any] = {"language": "en-US"}
        if self._tmdb_token:
            headers["Authorization"] = f"Bearer {self._tmdb_token}"
        elif self._tmdb_key:
            params["api_key"] = self._tmdb_key

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=headers, params=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"tmdb_status_{resp.status}: {body[:200]}")
                data = await resp.json()
        return list(data.get("cast") or [])

    async def _match_character(
        self,
        cast_character_name: str,
        *,
        universe: Optional[str],
        franchise: Optional[str],
    ) -> Optional[str]:
        """Find an existing character row scoped by universe/franchise."""
        async with get_session() as session:
            stmt = select(CharacterModel).where(
                CharacterModel.universe == universe,
            )
            rows = (await session.execute(stmt)).scalars().all()

        if not rows:
            return None

        target = cast_character_name.lower().strip()

        # Exact match within franchise scope first.
        if franchise:
            for r in rows:
                if (
                    (r.franchise or "").lower() == (franchise or "").lower()
                    and (r.name or "").lower() == target
                ):
                    return r.id
        # Exact match in universe (no franchise constraint).
        for r in rows:
            if (r.name or "").lower() == target:
                return r.id

        # Fuzzy match within franchise.
        best_id: Optional[str] = None
        best_score = 0
        for r in rows:
            if franchise and (r.franchise or "").lower() != (franchise or "").lower():
                continue
            score = _fuzzy_ratio(r.name or "", target)
            if score > best_score:
                best_score = score
                best_id = r.id
        if best_id and best_score >= 90:
            return best_id

        # Last-chance fuzzy across the universe.
        best_id = None
        best_score = 0
        for r in rows:
            score = _fuzzy_ratio(r.name or "", target)
            if score > best_score:
                best_score = score
                best_id = r.id
        if best_id and best_score >= 95:
            return best_id

        return None

    async def _create_stub_character(
        self,
        *,
        name: str,
        universe: Optional[str],
        franchise: Optional[str],
        source_title: str,
        actor_name: Optional[str],
    ) -> str:
        """Create a pending-status character row from a TMDB cast entry."""
        char_id = generate_id("char")
        note = f"auto-imported from TMDB cast of {source_title}"
        if actor_name:
            note += f" (played by {actor_name})"
        async with get_session() as session:
            session.add(CharacterModel(
                id=char_id,
                name=name,
                universe=universe or "other",
                franchise=franchise,
                research_status="pending",
                status="pending",
                discovery_source="tmdb_cast_sync",
                discovery_evidence={"source_title": source_title, "actor_name": actor_name},
                content_themes=[note],
                research_data={"auto_imported_note": note},
            ))
            try:
                await session.commit()
            except Exception:  # noqa: BLE001
                await session.rollback()
                # Possible race against duplicate name — fall back to a fresh match.
                fallback = await self._match_character(
                    name, universe=universe, franchise=franchise,
                )
                return fallback or char_id
        logger.info(
            "cast_sync_stub_created",
            character_id=char_id, name=name, source=source_title,
        )
        return char_id

    async def _upsert_link(
        self,
        *,
        character_id: str,
        media_title_id: str,
        role_name: str,
        role_type: str,
        actor_name: Optional[str],
        seasons_appeared: List[int],
    ) -> bool:
        """Insert a junction row. Returns True if a new row was inserted."""
        async with get_session() as session:
            existing = await session.execute(
                select(CharacterMediaTitleModel).where(
                    CharacterMediaTitleModel.character_id == character_id,
                    CharacterMediaTitleModel.media_title_id == media_title_id,
                )
            )
            row = existing.scalar_one_or_none()
            if row:
                # Refresh the metadata in case it was thin (cast list often
                # provides better role info than manual entries).
                if not row.actor_name and actor_name:
                    row.actor_name = actor_name
                if seasons_appeared and not (row.seasons_appeared or []):
                    row.seasons_appeared = seasons_appeared
                if role_name and not row.role_name:
                    row.role_name = role_name
                await session.commit()
                return False

            session.add(CharacterMediaTitleModel(
                id=generate_id("cml"),
                character_id=character_id,
                media_title_id=media_title_id,
                role_name=role_name,
                role_type=role_type,
                actor_name=actor_name,
                seasons_appeared=seasons_appeared,
                notes="auto-synced from TMDB cast",
            ))
            try:
                await session.commit()
                return True
            except Exception:  # noqa: BLE001
                await session.rollback()
                return False


_singleton: Optional[MediaCastSyncService] = None


def get_media_cast_sync_service() -> MediaCastSyncService:
    global _singleton
    if _singleton is None:
        _singleton = MediaCastSyncService()
    return _singleton
