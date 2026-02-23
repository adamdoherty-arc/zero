"""
Migrate ZERO workspace JSON data to PostgreSQL.

Reads all JSON files from workspace/ and inserts into the database.
Idempotent: uses INSERT ON CONFLICT DO NOTHING.

Usage:
    python -m scripts.migrate_json_to_postgres
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.infrastructure.config import get_settings
from app.infrastructure.database import init_database, close_database, get_session
from app.db.models import (
    ProjectModel, SprintModel, TaskModel,
    NoteModel, UserProfileModel, UserFactModel, UserContactModel,
    ResearchTopicModel, ResearchFindingModel, ResearchCycleModel,
    MoneyIdeaModel, EnhancementSignalModel,
    NotificationModel, ReminderModel,
    EmailCacheModel, CalendarEventCacheModel, SyncStatusModel,
    ServiceConfigModel, AgentStateModel,
)


def load_json(path: Path) -> Any:
    """Load a JSON file, return empty dict/list on failure."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  WARNING: Failed to load {path}: {e}")
        return {}


def to_snake(name: str) -> str:
    """Convert camelCase to snake_case."""
    import re
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


def normalize_keys(d: dict) -> dict:
    """Recursively convert camelCase keys to snake_case."""
    if not isinstance(d, dict):
        return d
    return {to_snake(k): normalize_keys(v) if isinstance(v, dict) else v for k, v in d.items()}


def parse_dt(val: Any) -> datetime | None:
    """Parse a datetime string, return None on failure."""
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    except Exception:
        return None


async def migrate_projects(workspace: Path, session):
    """Migrate projects.json → projects table."""
    data = load_json(workspace / "sprints" / "projects.json")
    projects = data if isinstance(data, list) else data.get("projects", [])
    count = 0
    for p in projects:
        p = normalize_keys(p)
        existing = await session.get(ProjectModel, p.get("id"))
        if existing:
            continue
        session.add(ProjectModel(
            id=p.get("id", ""),
            name=p.get("name", "Unknown"),
            description=p.get("description"),
            path=p.get("path", ""),
            project_type=p.get("project_type", p.get("type", "local")),
            status=p.get("status", "active"),
            tags=p.get("tags", []),
            created_at=parse_dt(p.get("created_at")) or datetime.utcnow(),
        ))
        count += 1
    await session.flush()
    print(f"  Projects: {count} inserted")


async def migrate_sprints(workspace: Path, session):
    """Migrate sprints.json → sprints table."""
    data = load_json(workspace / "sprints" / "sprints.json")
    sprints = data if isinstance(data, list) else data.get("sprints", [])
    count = 0
    for s in sprints:
        s = normalize_keys(s)
        sid = str(s.get("id", ""))
        existing = await session.get(SprintModel, sid)
        if existing:
            continue
        session.add(SprintModel(
            id=sid,
            number=s.get("number", 0),
            name=s.get("name", "Unnamed"),
            description=s.get("description"),
            status=s.get("status", "planning"),
            start_date=parse_dt(s.get("start_date")),
            end_date=parse_dt(s.get("end_date")),
            goals=s.get("goals", []),
            total_points=s.get("total_points", 0),
            completed_points=s.get("completed_points", 0),
            project_id=s.get("project_id"),
            project_name=s.get("project_name"),
            created_at=parse_dt(s.get("created_at")) or datetime.utcnow(),
        ))
        count += 1
    await session.flush()
    print(f"  Sprints: {count} inserted")


async def migrate_tasks(workspace: Path, session):
    """Migrate tasks.json → tasks table."""
    data = load_json(workspace / "sprints" / "tasks.json")
    tasks = data if isinstance(data, list) else data.get("tasks", [])
    count = 0
    for t in tasks:
        t = normalize_keys(t)
        tid = t.get("id", "")
        existing = await session.get(TaskModel, tid)
        if existing:
            continue
        session.add(TaskModel(
            id=tid,
            sprint_id=t.get("sprint_id"),
            project_id=t.get("project_id"),
            title=t.get("title", "Untitled"),
            description=t.get("description"),
            status=t.get("status", "backlog"),
            category=t.get("category", "feature"),
            priority=t.get("priority", "medium"),
            points=t.get("points"),
            source=t.get("source", "MANUAL"),
            source_reference=t.get("source_reference"),
            blocked_reason=t.get("blocked_reason"),
            created_at=parse_dt(t.get("created_at")) or datetime.utcnow(),
        ))
        count += 1
    await session.flush()
    print(f"  Tasks: {count} inserted")


async def migrate_notes(workspace: Path, session):
    """Migrate knowledge/notes.json → notes table."""
    data = load_json(workspace / "knowledge" / "notes.json")
    notes = data if isinstance(data, list) else data.get("notes", [])
    count = 0
    for n in notes:
        n = normalize_keys(n)
        nid = n.get("id", "")
        existing = await session.get(NoteModel, nid)
        if existing:
            continue
        session.add(NoteModel(
            id=nid,
            type=n.get("type", "note"),
            title=n.get("title"),
            content=n.get("content", ""),
            source=n.get("source", "manual"),
            tags=n.get("tags", []),
            project_id=n.get("project_id"),
            task_id=n.get("task_id"),
            created_at=parse_dt(n.get("created_at")) or datetime.utcnow(),
        ))
        count += 1
    await session.flush()
    print(f"  Notes: {count} inserted")


async def migrate_user_profile(workspace: Path, session):
    """Migrate knowledge/user.json → user_profile, user_facts, user_contacts."""
    data = load_json(workspace / "knowledge" / "user.json")
    if not data:
        print("  User profile: skipped (no data)")
        return

    data = normalize_keys(data)

    # Profile (singleton)
    existing = await session.get(UserProfileModel, 1)
    if not existing:
        session.add(UserProfileModel(
            id=1,
            name=data.get("name", "User"),
            timezone=data.get("timezone", "America/New_York"),
            preferences=data.get("preferences", {}),
            communication_style=data.get("communication_style"),
            interests=data.get("interests", []),
            skills=data.get("skills", []),
            goals=data.get("goals", []),
        ))
        print("  User profile: inserted")

    # Facts
    facts = data.get("facts", [])
    fact_count = 0
    for i, f in enumerate(facts):
        if isinstance(f, str):
            f = {"fact": f, "category": "general"}
        f = normalize_keys(f)
        fid = f.get("id", f"fact-{i+1}")
        existing = await session.get(UserFactModel, fid)
        if existing:
            continue
        session.add(UserFactModel(
            id=fid,
            fact=f.get("fact", str(f)),
            category=f.get("category", "general"),
            confidence=f.get("confidence", 1.0),
            source=f.get("source", "manual"),
        ))
        fact_count += 1
    await session.flush()
    print(f"  User facts: {fact_count} inserted")

    # Contacts
    contacts = data.get("contacts", [])
    contact_count = 0
    for c in contacts:
        c = normalize_keys(c)
        session.add(UserContactModel(
            name=c.get("name", "Unknown"),
            relation=c.get("relation"),
            email=c.get("email"),
            phone=c.get("phone"),
            notes=c.get("notes"),
        ))
        contact_count += 1
    await session.flush()
    print(f"  User contacts: {contact_count} inserted")


async def migrate_research(workspace: Path, session):
    """Migrate research/ → research tables."""
    # Topics
    data = load_json(workspace / "research" / "topics.json")
    topics = data if isinstance(data, list) else data.get("topics", [])
    tc = 0
    for t in topics:
        t = normalize_keys(t)
        tid = t.get("id", "")
        existing = await session.get(ResearchTopicModel, tid)
        if existing:
            continue
        session.add(ResearchTopicModel(
            id=tid,
            name=t.get("name", ""),
            description=t.get("description"),
            search_queries=t.get("search_queries", []),
            aspects=t.get("aspects", []),
            category_tags=t.get("category_tags", []),
            status=t.get("status", "active"),
            relevance_score=t.get("relevance_score", 50.0),
            created_at=parse_dt(t.get("created_at")) or datetime.utcnow(),
        ))
        tc += 1
    await session.flush()
    print(f"  Research topics: {tc} inserted")

    # Findings
    data = load_json(workspace / "research" / "findings.json")
    findings = data if isinstance(data, list) else data.get("findings", [])
    fc = 0
    for f in findings:
        f = normalize_keys(f)
        fid = f.get("id", "")
        existing = await session.get(ResearchFindingModel, fid)
        if existing:
            continue
        session.add(ResearchFindingModel(
            id=fid,
            topic_id=f.get("topic_id"),
            title=f.get("title", ""),
            url=f.get("url", ""),
            snippet=f.get("snippet", ""),
            status=f.get("status", "new"),
            relevance_score=f.get("relevance_score", 50.0),
            composite_score=f.get("composite_score", 50.0),
            llm_summary=f.get("llm_summary"),
            tags=f.get("tags", []),
            discovered_at=parse_dt(f.get("discovered_at")) or datetime.utcnow(),
        ))
        fc += 1
    await session.flush()
    print(f"  Research findings: {fc} inserted")

    # Cycles
    data = load_json(workspace / "research" / "cycles.json")
    cycles = data if isinstance(data, list) else data.get("cycles", [])
    cc = 0
    for c in cycles:
        c = normalize_keys(c)
        cid = c.get("id", "")
        existing = await session.get(ResearchCycleModel, cid)
        if existing:
            continue
        session.add(ResearchCycleModel(
            id=cid,
            started_at=parse_dt(c.get("started_at")) or datetime.utcnow(),
            completed_at=parse_dt(c.get("completed_at")),
            topics_researched=c.get("topics_researched", 0),
            new_findings=c.get("new_findings", 0),
            tasks_created=c.get("tasks_created", 0),
        ))
        cc += 1
    await session.flush()
    print(f"  Research cycles: {cc} inserted")


async def migrate_money_ideas(workspace: Path, session):
    """Migrate money-maker/ideas.json → money_ideas table."""
    data = load_json(workspace / "money-maker" / "ideas.json")
    ideas = data if isinstance(data, list) else data.get("ideas", [])
    count = 0
    for i in ideas:
        i = normalize_keys(i)
        iid = i.get("id", "")
        existing = await session.get(MoneyIdeaModel, iid)
        if existing:
            continue
        session.add(MoneyIdeaModel(
            id=iid,
            title=i.get("title", ""),
            description=i.get("description"),
            category=i.get("category", "other"),
            status=i.get("status", "new"),
            viability_score=i.get("viability_score", 0),
            generated_at=parse_dt(i.get("generated_at")) or datetime.utcnow(),
        ))
        count += 1
    await session.flush()
    print(f"  Money ideas: {count} inserted")


async def migrate_notifications(workspace: Path, session):
    """Migrate assistant/notifications.json → notifications table."""
    data = load_json(workspace / "assistant" / "notifications.json")
    notifications = data if isinstance(data, list) else data.get("notifications", [])
    count = 0
    for n in notifications:
        n = normalize_keys(n)
        nid = n.get("id", "")
        existing = await session.get(NotificationModel, nid)
        if existing:
            continue
        session.add(NotificationModel(
            id=nid,
            title=n.get("title", ""),
            message=n.get("message", ""),
            channel=n.get("channel", "ui"),
            read=n.get("read", False),
            source=n.get("source"),
            created_at=parse_dt(n.get("created_at")) or datetime.utcnow(),
        ))
        count += 1
    await session.flush()
    print(f"  Notifications: {count} inserted")


async def main():
    print("=" * 60)
    print("ZERO: JSON → PostgreSQL Data Migration")
    print("=" * 60)

    settings = get_settings()
    workspace = Path(settings.workspace_dir).resolve()
    print(f"Workspace: {workspace}")
    print(f"Database: {settings.postgres_url.split('@')[-1]}")
    print()

    await init_database(settings.postgres_url)

    # Create tables if they don't exist
    from app.infrastructure.database import create_tables
    await create_tables()

    async with get_session() as session:
        print("Migrating data...")
        await migrate_projects(workspace, session)
        await migrate_sprints(workspace, session)
        await migrate_tasks(workspace, session)
        await migrate_notes(workspace, session)
        await migrate_user_profile(workspace, session)
        await migrate_research(workspace, session)
        await migrate_money_ideas(workspace, session)
        await migrate_notifications(workspace, session)

    await close_database()

    print()
    print("Migration complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
