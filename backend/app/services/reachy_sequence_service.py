"""
Reachy custom motion sequences.

Stores user-defined chains of emotion/dance clips in the ``reachy_sequences``
table and plays them back by calling the daemon's play-recorded-move endpoint
step by step with configurable inter-step gaps.

Integrates with the motion library at the resolver layer: sequences share the
same name-or-alias namespace as hardcoded clips. A sequence named
``happy_greeting`` (or with alias ``hi``) resolves just like any emotion clip,
so the LLM's ``[emotion:happy_greeting]`` marker plays the whole chain.

The resolver keeps an in-memory cache of sequence names/aliases so the hot path
(every gesture the LLM emits) avoids a DB round-trip. The cache invalidates
after every create/update/delete.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Optional

import structlog
from sqlalchemy import select

from app.db.models import ReachySequenceModel
from app.infrastructure.database import get_session
from app.services.reachy_motion_library import (
    MotionClip,
    MotionKind,
    resolve_motion,
)

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Step model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SequenceStep:
    clip: str
    kind: MotionKind | None
    gap_ms: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SequenceStep":
        clip = str(data.get("clip") or "").strip()
        if not clip:
            raise ValueError("step missing 'clip'")
        raw_kind = data.get("kind")
        kind: MotionKind | None = None
        if raw_kind in ("emotion", "dance"):
            kind = raw_kind  # type: ignore[assignment]
        try:
            gap = int(data.get("gap_ms", 0))
        except (TypeError, ValueError):
            gap = 0
        gap = max(0, min(10_000, gap))
        return cls(clip=clip, kind=kind, gap_ms=gap)

    def to_dict(self) -> dict[str, Any]:
        return {"clip": self.clip, "kind": self.kind, "gap_ms": self.gap_ms}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

def _normalize(s: str) -> str:
    return "_".join((s or "").strip().lower().replace("-", " ").split())


class ReachySequenceService:
    """In-memory alias cache + DB-backed CRUD + playback."""

    def __init__(self) -> None:
        # name_or_alias_normalized -> sequence dict
        self._cache: dict[str, dict[str, Any]] = {}
        self._cache_ready: bool = False
        self._lock = asyncio.Lock()

    # ---- cache ---------------------------------------------------------

    async def _ensure_cache(self) -> None:
        if self._cache_ready:
            return
        async with self._lock:
            if self._cache_ready:
                return
            await self._reload_cache_locked()

    async def _reload_cache_locked(self) -> None:
        cache: dict[str, dict[str, Any]] = {}
        try:
            async with get_session() as session:
                rows = (
                    await session.execute(select(ReachySequenceModel))
                ).scalars().all()
                for row in rows:
                    d = _row_to_dict(row)
                    cache[_normalize(d["name"])] = d
                    for alias in d.get("aliases", []) or []:
                        key = _normalize(str(alias))
                        if key:
                            cache.setdefault(key, d)
            self._cache = cache
            self._cache_ready = True
            logger.info("reachy_sequence_cache_loaded", count=len(rows))
        except Exception as e:
            logger.warning("reachy_sequence_cache_load_failed", error=str(e))
            self._cache = {}
            self._cache_ready = False

    async def invalidate(self) -> None:
        async with self._lock:
            await self._reload_cache_locked()

    async def resolve(self, query: str) -> Optional[dict[str, Any]]:
        """Return a sequence dict if the query matches a saved sequence name/alias."""
        if not query:
            return None
        await self._ensure_cache()
        return self._cache.get(_normalize(query))

    # ---- CRUD ----------------------------------------------------------

    async def list_sequences(self) -> list[dict[str, Any]]:
        async with get_session() as session:
            rows = (
                await session.execute(
                    select(ReachySequenceModel).order_by(ReachySequenceModel.name)
                )
            ).scalars().all()
            return [_row_to_dict(r) for r in rows]

    async def get_sequence(self, id_or_name: str | int) -> Optional[dict[str, Any]]:
        async with get_session() as session:
            row = await _fetch_row(session, id_or_name)
            return _row_to_dict(row) if row else None

    async def create_sequence(
        self,
        *,
        name: str,
        description: Optional[str],
        steps: list[dict[str, Any]],
        aliases: list[str] | None = None,
    ) -> dict[str, Any]:
        name = name.strip()
        if not name:
            raise ValueError("name is required")
        aliases = [a.strip() for a in (aliases or []) if a and a.strip()]
        validated_steps = _validate_steps(steps)

        async with get_session() as session:
            existing = (
                await session.execute(
                    select(ReachySequenceModel).where(
                        ReachySequenceModel.name == name
                    )
                )
            ).scalar_one_or_none()
            if existing:
                raise ValueError(f"sequence with name {name!r} already exists")

            row = ReachySequenceModel(
                name=name,
                description=description,
                steps=[s.to_dict() for s in validated_steps],
                aliases=aliases,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            out = _row_to_dict(row)
        await self.invalidate()
        return out

    async def update_sequence(
        self,
        sequence_id: int,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        steps: Optional[list[dict[str, Any]]] = None,
        aliases: Optional[list[str]] = None,
    ) -> Optional[dict[str, Any]]:
        async with get_session() as session:
            row = await session.get(ReachySequenceModel, sequence_id)
            if not row:
                return None
            if name is not None:
                name = name.strip()
                if not name:
                    raise ValueError("name cannot be empty")
                clash = (
                    await session.execute(
                        select(ReachySequenceModel).where(
                            ReachySequenceModel.name == name,
                            ReachySequenceModel.id != sequence_id,
                        )
                    )
                ).scalar_one_or_none()
                if clash:
                    raise ValueError(f"sequence with name {name!r} already exists")
                row.name = name
            if description is not None:
                row.description = description
            if steps is not None:
                validated = _validate_steps(steps)
                row.steps = [s.to_dict() for s in validated]
            if aliases is not None:
                row.aliases = [a.strip() for a in aliases if a and a.strip()]
            await session.commit()
            await session.refresh(row)
            out = _row_to_dict(row)
        await self.invalidate()
        return out

    async def delete_sequence(self, sequence_id: int) -> bool:
        async with get_session() as session:
            row = await session.get(ReachySequenceModel, sequence_id)
            if not row:
                return False
            await session.delete(row)
            await session.commit()
        await self.invalidate()
        return True

    # ---- playback ------------------------------------------------------

    async def play_sequence(
        self,
        id_or_name: str | int,
        *,
        reachy_service: Any,
    ) -> dict[str, Any]:
        """
        Play a sequence end-to-end. Returns per-step results. Caller is
        responsible for passing the ReachyService (avoids circular import).
        """
        seq: Optional[dict[str, Any]] = None
        if isinstance(id_or_name, int):
            seq = await self.get_sequence(id_or_name)
        else:
            seq = await self.resolve(str(id_or_name))
            if not seq:
                seq = await self.get_sequence(str(id_or_name))
        if not seq:
            return {"error": f"unknown sequence: {id_or_name}"}
        from app.services.reachy_motion_policy import body_motion_allowed, body_motion_locked_payload

        if not body_motion_allowed(surface=f"sequence:{seq.get('name') or id_or_name}").get("allowed"):
            return body_motion_locked_payload(surface=f"sequence:{seq.get('name') or id_or_name}")

        results: list[dict[str, Any]] = []
        for idx, step_dict in enumerate(seq.get("steps", []) or []):
            step = SequenceStep.from_dict(step_dict)
            clip_result: dict[str, Any]
            try:
                if step.kind == "emotion":
                    clip_result = await reachy_service.play_emotion(step.clip)
                elif step.kind == "dance":
                    clip_result = await reachy_service.play_dance(step.clip)
                else:
                    clip_result = await reachy_service.play_motion(step.clip)
            except Exception as e:
                clip_result = {"error": f"step {idx} failed: {e}"}
            results.append(
                {
                    "index": idx,
                    "clip": step.clip,
                    "kind": step.kind,
                    "gap_ms": step.gap_ms,
                    "result": clip_result,
                }
            )
            if step.gap_ms > 0 and idx < len(seq["steps"]) - 1:
                await asyncio.sleep(step.gap_ms / 1000.0)

        return {
            "sequence_id": seq.get("id"),
            "name": seq.get("name"),
            "steps_played": len(results),
            "results": results,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row: ReachySequenceModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "steps": list(row.steps or []),
        "aliases": list(row.aliases or []),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _fetch_row(session, id_or_name: str | int) -> Optional[ReachySequenceModel]:
    try:
        as_int = int(id_or_name)
        row = await session.get(ReachySequenceModel, as_int)
        if row:
            return row
    except (TypeError, ValueError):
        pass
    name = str(id_or_name).strip()
    if not name:
        return None
    return (
        await session.execute(
            select(ReachySequenceModel).where(ReachySequenceModel.name == name)
        )
    ).scalar_one_or_none()


def _validate_steps(steps: list[dict[str, Any]]) -> list[SequenceStep]:
    """
    Parse + validate. Each step's clip must resolve against the hardcoded
    motion library (no nested sequences — keeps playback non-recursive).
    Raises ValueError with all invalid clips listed.
    """
    if not steps:
        raise ValueError("sequence must have at least one step")

    parsed: list[SequenceStep] = []
    unknown: list[str] = []
    for i, raw in enumerate(steps):
        try:
            step = SequenceStep.from_dict(raw)
        except Exception as e:
            raise ValueError(f"step {i}: {e}")
        # Validate the clip resolves. Constrain kind if caller specified one.
        clip: Optional[MotionClip] = resolve_motion(step.clip, kind=step.kind)
        if not clip:
            unknown.append(step.clip)
            parsed.append(step)
            continue
        # Normalize kind to the resolved clip's kind so playback dispatches correctly.
        if step.kind is None:
            step = SequenceStep(clip=clip.name, kind=clip.kind, gap_ms=step.gap_ms)
        else:
            step = SequenceStep(clip=clip.name, kind=step.kind, gap_ms=step.gap_ms)
        parsed.append(step)

    if unknown:
        raise ValueError(f"unknown clips: {', '.join(sorted(set(unknown)))}")
    return parsed


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_service: Optional[ReachySequenceService] = None


def get_reachy_sequence_service() -> ReachySequenceService:
    global _service
    if _service is None:
        _service = ReachySequenceService()
    return _service
