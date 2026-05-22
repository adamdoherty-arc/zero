"""F-47 — resolve cross-project references in meeting titles + descriptions.

Given a meeting title + description + transcript chunk, find any
mentions of:

  - Legion sprint slugs (Feature-NN / Enhancement-NN / Fix-NN / Perf-NN /
    Refactor-NN / Migration-NN)
  - ADA AI projects / Zero personal-board items (by exact title match)

Used by the prep brief to surface 'related sprints / projects' so when
a meeting mentions Feature-37 the user has the context inline.

Pure lookup — no LLM. Cached for 60 s per process to keep prep-brief
composition cheap.
"""

from __future__ import annotations

import re
import time
from functools import lru_cache
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


_SPRINT_SLUG_RE = re.compile(
    r"\b(Feature|Enhancement|Fix|Perf|Refactor|Migration|Plan)-(\d{1,4})\b",
    re.IGNORECASE,
)


class MeetingXProjectResolver:
    def __init__(self) -> None:
        self._cache_sprints: dict[str, dict[str, Any]] | None = None
        self._cache_sprints_at: float = 0.0
        self._cache_pb: list[dict[str, Any]] | None = None
        self._cache_pb_at: float = 0.0
        self._cache_ada: list[dict[str, Any]] | None = None
        self._cache_ada_at: float = 0.0
        self._ttl_s: float = 60.0

    async def _all_legion_sprints(self) -> dict[str, dict[str, Any]]:
        now = time.monotonic()
        if self._cache_sprints is not None and now - self._cache_sprints_at < self._ttl_s:
            return self._cache_sprints
        try:
            from app.services.legion_client import get_legion_client

            client = get_legion_client()
            sprints = await client.list_sprints(project_id=7, status=None)
        except Exception as exc:
            logger.debug("xproject_resolver_legion_unreachable", error=str(exc))
            return self._cache_sprints or {}
        index: dict[str, dict[str, Any]] = {}
        for s in sprints or []:
            slug = (s.get("slug") or "").lower()
            if slug:
                index[slug] = {
                    "id": s.get("id"),
                    "slug": s.get("slug"),
                    "name": s.get("name"),
                    "status": s.get("status"),
                    "project_id": s.get("project_id"),
                }
        self._cache_sprints = index
        self._cache_sprints_at = now
        return index

    async def _all_ada_projects(self) -> list[dict[str, Any]]:
        """F-35 — pull ADA company work items so meeting titles that
        mention an ADA project surface as a related-project link."""
        now = time.monotonic()
        if self._cache_ada is not None and now - self._cache_ada_at < self._ttl_s:
            return self._cache_ada
        try:
            from app.services.company_work_item_service import (
                get_company_work_item_service,
            )

            svc = get_company_work_item_service()
            try:
                items = await svc.list_open()  # type: ignore[attr-defined]
            except AttributeError:
                try:
                    items = await svc.list_all()  # type: ignore[attr-defined]
                except AttributeError:
                    items = []
        except Exception as exc:
            logger.debug("xproject_resolver_ada_unreachable", error=str(exc))
            items = []
        self._cache_ada = list(items or [])
        self._cache_ada_at = now
        return self._cache_ada

    async def _all_personal_board(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        if self._cache_pb is not None and now - self._cache_pb_at < self._ttl_s:
            return self._cache_pb
        try:
            from app.services.personal_work_item_service import (
                get_personal_work_item_service,
            )

            svc = get_personal_work_item_service()
            try:
                items = await svc.list(limit=200)  # type: ignore[attr-defined]
            except AttributeError:
                items = []
            self._cache_pb = list(items or [])
            self._cache_pb_at = now
            return self._cache_pb
        except Exception as exc:
            logger.debug("xproject_resolver_personal_board_unreachable", error=str(exc))
            self._cache_pb = []
            self._cache_pb_at = now
            return self._cache_pb

    async def resolve(
        self,
        *,
        title: str | None,
        description: str | None = None,
        transcript_chunk: str | None = None,
    ) -> dict[str, Any]:
        haystack = " ".join(filter(None, (title or "", description or "", transcript_chunk or "")))

        legion_sprints: list[dict[str, Any]] = []
        seen_slugs: set[str] = set()
        for m in _SPRINT_SLUG_RE.finditer(haystack):
            cat = m.group(1)
            num = m.group(2)
            slug = f"{cat[0].upper() + cat[1:].lower()}-{int(num):02d}"
            if slug.lower() in seen_slugs:
                continue
            seen_slugs.add(slug.lower())
        if seen_slugs:
            index = await self._all_legion_sprints()
            for slug in seen_slugs:
                hit = index.get(slug)
                if hit:
                    legion_sprints.append(hit)
                else:
                    legion_sprints.append({"slug": slug, "found": False})

        personal_board: list[dict[str, Any]] = []
        if title:
            items = await self._all_personal_board()
            title_lower = title.lower()
            for item in items:
                item_title = str(item.get("title") or "")
                if item_title and item_title.lower() in title_lower:
                    personal_board.append({
                        "id": item.get("id"),
                        "title": item_title,
                        "domain": item.get("domain"),
                    })

        # F-35 — ADA company work items: same exact-substring match as
        # personal-board so a meeting "Q3 financials with ADA-PROJECT-X"
        # surfaces the linked work item alongside.
        ada_projects: list[dict[str, Any]] = []
        if haystack:
            items = await self._all_ada_projects()
            haystack_lower = haystack.lower()
            for item in items:
                item_title = str(item.get("title") or item.get("name") or "")
                if not item_title:
                    continue
                if item_title.lower() in haystack_lower:
                    ada_projects.append({
                        "id": item.get("id"),
                        "title": item_title,
                        "status": item.get("status"),
                        "domain": item.get("domain"),
                    })

        return {
            "legion_sprints": legion_sprints,
            "personal_board": personal_board,
            "ada_projects": ada_projects,
        }


@lru_cache()
def get_meeting_xproject_resolver() -> MeetingXProjectResolver:
    return MeetingXProjectResolver()
