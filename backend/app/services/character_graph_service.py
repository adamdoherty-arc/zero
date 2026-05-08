"""
Character Graph Service.

Walks the relationship/franchise/universe graph that ties characters to each
other and to TV/movie media titles. Surfaces "team-up", "rivalry", and
"franchise crossover" carousel ideas that the swarm/breeder otherwise can't
discover, because that data is not available to the per-character generation
prompt.

Reads only — does not generate carousels itself. Callers (content_swarm_service,
scheduler jobs, future router endpoints) consume the returned ideas.
"""

from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import structlog
from sqlalchemy import select

from app.db.models import CharacterModel
from app.infrastructure.database import get_session

logger = structlog.get_logger()


class CharacterGraphService:
    """Build crossover ideas from the character relationship graph."""

    async def list_franchise_clusters(
        self, min_size: int = 2, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Group active characters by (universe, franchise) and return clusters
        with at least `min_size` members. Useful for franchise spotlight carousels."""
        async with get_session() as session:
            rows = (await session.execute(
                select(
                    CharacterModel.id,
                    CharacterModel.name,
                    CharacterModel.universe,
                    CharacterModel.franchise,
                ).where(CharacterModel.status == "active")
            )).all()

        buckets: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        for cid, name, universe, franchise in rows:
            if not franchise:
                continue
            buckets[(universe or "other", franchise)].append(
                {"id": cid, "name": name}
            )

        clusters: List[Dict[str, Any]] = []
        for (universe, franchise), members in buckets.items():
            if len(members) < min_size:
                continue
            clusters.append({
                "universe": universe,
                "franchise": franchise,
                "size": len(members),
                "characters": members[:20],
            })
        clusters.sort(key=lambda c: c["size"], reverse=True)
        return clusters[:limit]

    async def find_relationship_pairs(
        self,
        relation_types: Optional[List[str]] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Walk every character's relationship_map and emit pairs where both
        sides are active characters in the DB. relation_types filters the kind
        (e.g. 'rival', 'ally', 'mentor'); None returns all."""
        relation_types_set = set(relation_types or [])
        async with get_session() as session:
            rows = (await session.execute(
                select(
                    CharacterModel.id,
                    CharacterModel.name,
                    CharacterModel.universe,
                    CharacterModel.relationship_map,
                ).where(CharacterModel.status == "active")
            )).all()

        by_name = {r[1].lower(): {"id": r[0], "name": r[1], "universe": r[2]} for r in rows}
        pairs: List[Dict[str, Any]] = []
        seen: set = set()
        for cid, name, universe, rel_map in rows:
            if not isinstance(rel_map, dict):
                continue
            for rel_type, targets in rel_map.items():
                if relation_types_set and rel_type not in relation_types_set:
                    continue
                if not isinstance(targets, list):
                    continue
                for target in targets:
                    target_name = (target if isinstance(target, str) else target.get("name", "")).strip()
                    if not target_name:
                        continue
                    other = by_name.get(target_name.lower())
                    if not other or other["id"] == cid:
                        continue
                    key = tuple(sorted([cid, other["id"]])) + (rel_type,)
                    if key in seen:
                        continue
                    seen.add(key)
                    pairs.append({
                        "left": {"id": cid, "name": name, "universe": universe},
                        "right": other,
                        "relation": rel_type,
                    })
                    if len(pairs) >= limit:
                        return pairs
        return pairs

    async def propose_crossover_carousels(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return a ranked list of crossover/team-up/rivalry carousel ideas
        ready to feed into the content swarm or scheduler."""
        ideas: List[Dict[str, Any]] = []

        rivalries = await self.find_relationship_pairs(relation_types=["rival", "enemy", "nemesis"], limit=limit * 2)
        for pair in rivalries:
            ideas.append({
                "kind": "rivalry",
                "angle": "vs_comparison",
                "characters": [pair["left"], pair["right"]],
                "title_seed": f"{pair['left']['name']} vs {pair['right']['name']}",
            })

        team_ups = await self.find_relationship_pairs(relation_types=["ally", "team", "friend"], limit=limit * 2)
        for pair in team_ups:
            ideas.append({
                "kind": "team_up",
                "angle": "crossover_connections",
                "characters": [pair["left"], pair["right"]],
                "title_seed": f"{pair['left']['name']} + {pair['right']['name']}",
            })

        clusters = await self.list_franchise_clusters(min_size=3, limit=limit)
        for cluster in clusters:
            ideas.append({
                "kind": "franchise_spotlight",
                "angle": "timeline_deep_dive",
                "franchise": cluster["franchise"],
                "universe": cluster["universe"],
                "characters": cluster["characters"][:5],
                "title_seed": f"Every {cluster['franchise']} character ranked",
            })

        return ideas[:limit]


@lru_cache(maxsize=1)
def get_character_graph_service() -> CharacterGraphService:
    return CharacterGraphService()
