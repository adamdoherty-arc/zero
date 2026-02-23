"""
Notion integration service for Zero.

Provides CRUD operations on Notion databases and pages,
plus domain-specific sync methods for sprints, tasks, and meeting notes.
"""

import structlog
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone

from app.infrastructure.circuit_breaker import get_circuit_breaker

logger = structlog.get_logger()


class NotionService:
    """Service for Notion API operations."""

    def __init__(self, api_key: str, default_database_id: Optional[str] = None):
        self.api_key = api_key
        self.default_database_id = default_database_id
        self._client = None
        self._breaker = get_circuit_breaker(
            "notion",
            failure_threshold=3,
            recovery_timeout=120.0,
        )

    def _get_client(self):
        """Lazy-initialize the Notion async client."""
        if self._client is None:
            try:
                from notion_client import AsyncClient
                self._client = AsyncClient(auth=self.api_key)
                logger.info("notion_client_initialized")
            except ImportError:
                logger.error("notion_client_not_installed", hint="pip install notion-client")
                raise
        return self._client

    async def get_database(self, database_id: Optional[str] = None) -> Dict[str, Any]:
        """Fetch a Notion database by ID."""
        client = self._get_client()
        db_id = database_id or self.default_database_id
        if not db_id:
            raise ValueError("No database_id provided and no default configured")

        async def _retrieve():
            return await client.databases.retrieve(database_id=db_id)

        result = await self._breaker.call(_retrieve)
        logger.info("notion_database_retrieved", database_id=db_id)
        return result

    async def query_database(
        self,
        database_id: Optional[str] = None,
        filter: Optional[Dict] = None,
        sorts: Optional[List[Dict]] = None,
    ) -> List[Dict[str, Any]]:
        """Query pages from a Notion database."""
        client = self._get_client()
        db_id = database_id or self.default_database_id
        if not db_id:
            raise ValueError("No database_id provided")

        kwargs: Dict[str, Any] = {"database_id": db_id}
        if filter:
            kwargs["filter"] = filter
        if sorts:
            kwargs["sorts"] = sorts

        async def _query():
            return await client.databases.query(**kwargs)

        result = await self._breaker.call(_query)
        pages = result.get("results", [])
        logger.info("notion_database_queried", database_id=db_id, results=len(pages))
        return pages

    async def create_page(
        self,
        parent_id: str,
        properties: Dict[str, Any],
        children: Optional[List[Dict]] = None,
        is_database: bool = True,
    ) -> Dict[str, Any]:
        """Create a page in Notion."""
        client = self._get_client()
        parent = {"database_id": parent_id} if is_database else {"page_id": parent_id}
        kwargs: Dict[str, Any] = {"parent": parent, "properties": properties}
        if children:
            kwargs["children"] = children

        async def _create():
            return await client.pages.create(**kwargs)

        result = await self._breaker.call(_create)
        logger.info("notion_page_created", page_id=result["id"])
        return result

    async def update_page(
        self, page_id: str, properties: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update page properties."""
        client = self._get_client()

        async def _update():
            return await client.pages.update(page_id=page_id, properties=properties)

        result = await self._breaker.call(_update)
        logger.info("notion_page_updated", page_id=page_id)
        return result

    async def get_page(self, page_id: str) -> Dict[str, Any]:
        """Get a page by ID."""
        client = self._get_client()

        async def _get():
            return await client.pages.retrieve(page_id=page_id)

        return await self._breaker.call(_get)

    # =========================================================================
    # Domain-Specific Sync Methods
    # =========================================================================

    async def sync_sprint_to_notion(
        self, sprint_data: Dict[str, Any], database_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create or update a Notion page for a sprint."""
        db_id = database_id or self.default_database_id
        if not db_id:
            raise ValueError("No database_id for sprint sync")

        properties = {
            "Name": {"title": [{"text": {"content": sprint_data.get("name", "Untitled Sprint")}}]},
            "Status": {"select": {"name": sprint_data.get("status", "planned")}},
        }
        if sprint_data.get("description"):
            properties["Description"] = {
                "rich_text": [{"text": {"content": sprint_data["description"][:2000]}}]
            }

        # Check for existing page by sprint name
        existing = await self.query_database(
            database_id=db_id,
            filter={
                "property": "Name",
                "title": {"equals": sprint_data.get("name", "")},
            },
        )

        if existing:
            return await self.update_page(existing[0]["id"], properties)
        else:
            return await self.create_page(db_id, properties)

    async def sync_tasks_to_notion(
        self, tasks: List[Dict[str, Any]], database_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Upsert task rows into a Notion database."""
        db_id = database_id or self.default_database_id
        if not db_id:
            raise ValueError("No database_id for task sync")

        results = []
        for task in tasks:
            properties = {
                "Name": {"title": [{"text": {"content": task.get("title", "Untitled Task")}}]},
                "Status": {"select": {"name": task.get("status", "pending")}},
            }
            if task.get("description"):
                properties["Description"] = {
                    "rich_text": [{"text": {"content": task["description"][:2000]}}]
                }

            # Check if task already synced
            existing = await self.query_database(
                database_id=db_id,
                filter={
                    "property": "Name",
                    "title": {"equals": task.get("title", "")},
                },
            )

            if existing:
                result = await self.update_page(existing[0]["id"], properties)
            else:
                result = await self.create_page(db_id, properties)
            results.append(result)

        logger.info("notion_tasks_synced", count=len(results))
        return results

    async def pull_from_notion(
        self, database_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Pull items from a Notion database as task-like dicts."""
        pages = await self.query_database(database_id=database_id)
        items = []
        for page in pages:
            props = page.get("properties", {})
            title_prop = props.get("Name", {}).get("title", [])
            title = title_prop[0]["text"]["content"] if title_prop else "Untitled"
            status_prop = props.get("Status", {}).get("select", {})
            status = status_prop.get("name", "unknown") if status_prop else "unknown"
            items.append({
                "notion_page_id": page["id"],
                "title": title,
                "status": status,
                "url": page.get("url", ""),
                "last_edited": page.get("last_edited_time", ""),
            })
        return items

    async def create_meeting_notes(
        self,
        title: str,
        date: str,
        attendees: List[str],
        notes: str,
        parent_page_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a meeting notes page in Notion."""
        parent_id = parent_page_id or self.default_database_id
        if not parent_id:
            raise ValueError("No parent for meeting notes")

        properties = {
            "Name": {"title": [{"text": {"content": f"Meeting: {title} ({date})"}}]},
        }

        children = [
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"text": {"content": "Attendees"}}]},
            },
            {
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"text": {"content": ", ".join(attendees)}}]
                },
            },
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"text": {"content": "Notes"}}]},
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"text": {"content": notes}}]},
            },
        ]

        is_db = parent_id == self.default_database_id
        return await self.create_page(parent_id, properties, children=children, is_database=is_db)

    async def search_knowledge_base(self, query: str) -> List[Dict[str, Any]]:
        """Search Notion pages by title/content."""
        client = self._get_client()

        async def _search():
            return await client.search(query=query, page_size=20)

        result = await self._breaker.call(_search)
        pages = result.get("results", [])
        return [
            {
                "id": p["id"],
                "title": self._extract_title(p),
                "url": p.get("url", ""),
                "last_edited": p.get("last_edited_time", ""),
                "type": p.get("object", "page"),
            }
            for p in pages
            if p.get("object") == "page"
        ]

    async def sync_calendar_events_to_notion(
        self, events: List[Dict[str, Any]], database_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Create Notion pages for calendar events."""
        db_id = database_id or self.default_database_id
        if not db_id:
            raise ValueError("No database_id for calendar sync")

        results = []
        for event in events:
            properties = {
                "Name": {"title": [{"text": {"content": event.get("summary", "Untitled Event")}}]},
                "Status": {"select": {"name": "scheduled"}},
            }
            if event.get("start", {}).get("dateTime"):
                properties["Date"] = {
                    "date": {"start": event["start"]["dateTime"]}
                }
            result = await self.create_page(db_id, properties)
            results.append(result)

        logger.info("notion_calendar_events_synced", count=len(results))
        return results

    # =========================================================================
    # Bidirectional Sync
    # =========================================================================

    async def detect_notion_changes(self, since_minutes: int = 30) -> List[Dict[str, Any]]:
        """Detect Notion pages edited within the last `since_minutes`."""
        client = self._get_client()
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)

        async def _inner():
            result = await client.search(
                filter={"property": "object", "value": "page"},
                sort={"direction": "descending", "timestamp": "last_edited_time"},
            )
            pages = result.get("results", [])
            changed: List[Dict[str, Any]] = []
            for page in pages:
                edited_str = page.get("last_edited_time", "")
                if not edited_str:
                    continue
                # Parse ISO-8601 timestamp from Notion
                edited_dt = datetime.fromisoformat(edited_str.replace("Z", "+00:00"))
                if edited_dt < cutoff:
                    # Results are sorted descending by last_edited_time,
                    # so once we pass the cutoff we can stop.
                    break
                changed.append({
                    "page_id": page["id"],
                    "title": self._extract_title(page),
                    "last_edited_time": edited_str,
                    "url": page.get("url", ""),
                })
            return changed

        return await self._breaker.call(_inner)

    async def sync_bidirectional(self) -> Dict[str, Any]:
        """
        Bidirectional sync between Notion and local knowledge notes.

        - Detects recently edited Notion pages (last 30 min).
        - Matches by title to local notes in the DB.
        - Uses last-writer-wins: if Notion page is newer, update local note.
        - Returns sync statistics.
        """
        from app.infrastructure.database import get_session
        from app.db.models import NoteModel
        from sqlalchemy import select

        stats = {"pages_checked": 0, "synced_from_notion": 0, "conflicts": 0}

        try:
            changed_pages = await self.detect_notion_changes(30)
        except Exception as e:
            logger.error("notion_detect_changes_failed", error=str(e))
            return stats

        stats["pages_checked"] = len(changed_pages)
        if not changed_pages:
            return stats

        client = self._get_client()

        async with get_session() as session:
            for page in changed_pages:
                title = page["title"]
                if not title or title == "Untitled":
                    continue

                # Find matching local note by title
                result = await session.execute(
                    select(NoteModel).where(NoteModel.title == title).limit(1)
                )
                note = result.scalar_one_or_none()
                if note is None:
                    continue

                # Parse Notion edit time
                notion_edited = datetime.fromisoformat(
                    page["last_edited_time"].replace("Z", "+00:00")
                )

                # Compare with local updated_at (or created_at as fallback)
                local_updated = note.updated_at or note.created_at
                if local_updated and local_updated.tzinfo is None:
                    local_updated = local_updated.replace(tzinfo=timezone.utc)

                if local_updated and notion_edited <= local_updated:
                    # Local is newer or equal -- skip
                    continue

                # Notion is newer -- fetch page content blocks
                try:
                    async def _get_blocks(pid=page["page_id"]):
                        return await client.blocks.children.list(block_id=pid)

                    blocks_result = await self._breaker.call(_get_blocks)
                    blocks = blocks_result.get("results", [])

                    # Extract text from paragraph blocks
                    content_parts: List[str] = []
                    for block in blocks:
                        btype = block.get("type", "")
                        rich_texts = block.get(btype, {}).get("rich_text", [])
                        for rt in rich_texts:
                            text = rt.get("text", {}).get("content", "")
                            if text:
                                content_parts.append(text)

                    if content_parts:
                        note.content = "\n".join(content_parts)
                        note.updated_at = datetime.now(timezone.utc)
                        stats["synced_from_notion"] += 1
                        logger.info(
                            "notion_sync_updated_local_note",
                            title=title,
                            page_id=page["page_id"],
                        )
                    else:
                        stats["conflicts"] += 1
                        logger.warning(
                            "notion_sync_empty_content",
                            title=title,
                            page_id=page["page_id"],
                        )

                except Exception as e:
                    stats["conflicts"] += 1
                    logger.warning(
                        "notion_sync_conflict",
                        title=title,
                        page_id=page["page_id"],
                        error=str(e),
                    )

        logger.info("notion_bidirectional_sync_complete", **stats)
        return stats

    @staticmethod
    def _extract_title(page: Dict) -> str:
        """Extract title from a Notion page object."""
        props = page.get("properties", {})
        for key, val in props.items():
            if val.get("type") == "title":
                titles = val.get("title", [])
                if titles:
                    return titles[0].get("text", {}).get("content", "Untitled")
        return "Untitled"


# Singleton
_notion_service: Optional[NotionService] = None


def get_notion_service() -> Optional[NotionService]:
    """Get singleton NotionService, or None if not configured."""
    global _notion_service
    if _notion_service is not None:
        return _notion_service

    from app.infrastructure.config import get_settings
    settings = get_settings()
    if not settings.notion_api_key:
        logger.debug("notion_not_configured", hint="Set ZERO_NOTION_API_KEY")
        return None

    _notion_service = NotionService(
        api_key=settings.notion_api_key,
        default_database_id=settings.notion_database_id,
    )
    return _notion_service
