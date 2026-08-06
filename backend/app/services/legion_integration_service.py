"""
Legion Integration Service for Zero.
Sprint 43: Proactive intelligence linking Zero's data sources to Legion tasks.

Capabilities:
- Enhancement signals -> Legion tasks (T78), routed to the signal's OWN project
- Email action items -> Legion tasks (T79)
- Blocked task escalation via Discord (T81)

History (Fix-160, 2026-08-01): this module was overwritten on 2026-02-22 by a
17-line stub importing a package (`app.enums`) that has never existed. Every
caller therefore raised ModuleNotFoundError for ~5.5 months behind
`except Exception` handlers, silently disabling five scheduler jobs -- including
`autonomous_enhancement_cycle`, which died 13ms into its 09:00 run while the job
audit recorded `status=completed`. Restored here against the CURRENT service
APIs (the pre-stub version called several methods that have since been renamed
or removed).

Two capabilities from the original were deliberately NOT restored because the
codebase grew real replacements for them:
- `create_meeting_prep_tasks` -- its handler was never registered in the
  scheduler's job map, so it had no trigger even before the stub landed.
- `generate_smart_suggestions` -- `briefing_service._generate_ai_suggestions`
  computes the same thing inline at 07:00 and populates `DailyBriefing.suggestions`;
  the cached copy this produced had zero readers.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import select

from app.infrastructure.config import get_settings

logger = structlog.get_logger(__name__)

# Zero project ID in Legion (7 -- `SELECT id FROM projects WHERE name='Zero Personal Assistant'`)
ZERO_PROJECT_ID = get_settings().zero_legion_project_id

# Cap tasks created per run. Without this, the first successful tick after the
# 5.5-month outage would have filed the entire pending backlog (630 signals at
# the time of the fix, 617 of them ADA's) into Legion in one burst.
MAX_TASKS_PER_RUN = 25

# The escalation cache is keyed by task id and only used for a 24h cooldown, so
# entries older than the cooldown are dead weight. Bound it so a long-lived
# process cannot accumulate one entry per blocked task ever seen.
_ESCALATION_CACHE_MAX = 500


class LegionIntegrationService:
    """
    Proactive intelligence service connecting Zero's data sources
    (email, calendar, enhancement scanner) to Legion task management.
    """

    def __init__(self):
        self._blocked_task_cache: Dict[Any, datetime] = {}

    # =========================================================================
    # T78: Enhancement Signals -> Legion Tasks
    # =========================================================================

    async def auto_create_enhancement_tasks(
        self,
        confidence_threshold: float = 0.75,
        multi_project: bool = True,
    ) -> Dict[str, Any]:
        """
        Convert high-confidence pending enhancement signals into Legion tasks.

        Each signal is filed into the Legion project it was DETECTED in, not into
        Zero. The pre-stub version resolved that mapping through
        `SCAN_PROJECTS[...]["legion_id"]`, where all four ids were off by one into
        a real neighbouring project -- ADA's signals would have landed in
        "FortressOS Job Platform", Zero's in "AI Content Tools". Those ids are
        corrected in enhancement_service; this method skips any signal whose
        project it cannot map rather than defaulting to Zero.
        """
        from app.services.enhancement_service import get_enhancement_service, SCAN_PROJECTS
        from app.services.legion_client import get_legion_client
        from app.db.models import EnhancementSignalModel
        from app.infrastructure.database import get_session

        enhancement_svc = get_enhancement_service()
        legion = get_legion_client()

        if not await legion.health_check():
            return {"status": "legion_unavailable", "tasks_created": 0}

        # Refresh signals first so we act on current state.
        if multi_project:
            scan_result = await enhancement_svc.scan_all_projects()
        else:
            scan_result = await enhancement_svc.scan_for_signals()

        min_confidence = confidence_threshold * 100
        project_id_map = {name: cfg["legion_id"] for name, cfg in SCAN_PROJECTS.items()}

        # --- Tx-A: read candidates, then release the session ------------------
        # Signals live in Postgres. The pre-stub version read them from a JSON
        # file via `enhancement_svc.storage`, an attribute that no longer exists
        # (it is None on the instance), so that path would have AttributeError'd
        # even with the import fixed.
        candidates: List[Dict[str, Any]] = []
        skipped_low_confidence = 0
        skipped_unmapped = 0

        async with get_session() as session:
            result = await session.execute(
                select(EnhancementSignalModel)
                .where(EnhancementSignalModel.status == "pending")
                .order_by(EnhancementSignalModel.priority_score.desc())
            )
            for row in result.scalars().all():
                if (row.confidence or 0) < min_confidence:
                    skipped_low_confidence += 1
                    continue
                proj_name = row.project_name or "zero"
                if proj_name not in project_id_map:
                    # Unknown project: skip rather than silently defaulting to
                    # Zero, which would file another project's debt as ours.
                    skipped_unmapped += 1
                    continue
                if len(candidates) >= MAX_TASKS_PER_RUN:
                    continue
                candidates.append({
                    "id": row.id,
                    "project_name": proj_name,
                    "project_id": project_id_map[proj_name],
                    "type": row.type,
                    "message": row.message,
                    "severity": row.severity,
                    "confidence": row.confidence,
                    "source_file": row.source_file,
                    "line_number": row.line_number,
                    "context": row.context,
                })

        # --- Network phase: no DB session held across these awaits ------------
        # (backend rule: never hold a session across a network await)
        converted: List[Dict[str, Any]] = []
        per_project_created: Dict[str, int] = {}
        sprint_cache: Dict[int, Dict] = {}

        for sig in candidates:
            project_id = sig["project_id"]
            if project_id not in sprint_cache:
                sprint = await self._get_or_create_sprint(
                    legion, project_id, "Enhancement", "Auto: Enhancement Signals"
                )
                if not sprint:
                    continue
                sprint_cache[project_id] = sprint
            sprint = sprint_cache[project_id]

            task_data = {
                "title": f"[{(sig['type'] or 'todo').upper()}] {(sig['message'] or '')[:100]}",
                "description": (
                    f"Source: {sig['source_file']}:{sig['line_number']}\n"
                    f"Project: {sig['project_name']}\n"
                    f"Confidence: {sig['confidence']}%\n"
                    f"Context: {(sig['context'] or 'N/A')[:200]}"
                ),
                "priority": self._severity_to_priority(sig["severity"] or "medium"),
                "source": "enhancement_scanner",
            }

            try:
                task = await legion.create_task(sprint["id"], task_data)
            except Exception as e:
                logger.warning(
                    "enhancement_task_create_failed",
                    error=str(e),
                    project=sig["project_name"],
                )
                continue

            converted.append({"signal_id": sig["id"], "legion_task_id": task.get("id")})
            per_project_created[sig["project_name"]] = (
                per_project_created.get(sig["project_name"], 0) + 1
            )

        # --- Tx-C: persist the conversions ------------------------------------
        # The pre-stub version mutated an in-memory dict and wrote it back to the
        # JSON store, so against the DB-backed model it would have re-filed the
        # same signals on every tick, unboundedly.
        if converted:
            now = datetime.now(timezone.utc)
            async with get_session() as session:
                rows = await session.execute(
                    select(EnhancementSignalModel).where(
                        EnhancementSignalModel.id.in_([c["signal_id"] for c in converted])
                    )
                )
                task_by_signal = {c["signal_id"]: c["legion_task_id"] for c in converted}
                for row in rows.scalars().all():
                    row.status = "converted"
                    row.converted_to_legion_task = task_by_signal.get(row.id)
                    row.converted_at = now
                await session.commit()

        logger.info(
            "enhancement_auto_tasks",
            scanned=scan_result.get("signals_found", 0),
            created=len(converted),
            skipped_low_confidence=skipped_low_confidence,
            skipped_unmapped=skipped_unmapped,
            per_project=per_project_created,
        )

        return {
            "status": "completed",
            "signals_scanned": scan_result.get("signals_found", 0),
            "tasks_created": len(converted),
            "skipped_low_confidence": skipped_low_confidence,
            "skipped_unmapped": skipped_unmapped,
            "per_project": per_project_created,
            "capped": len(candidates) >= MAX_TASKS_PER_RUN,
        }

    # =========================================================================
    # T79: Email -> Legion Task Conversion
    # =========================================================================

    async def convert_emails_to_tasks(self) -> Dict[str, Any]:
        """
        Analyze recent unread emails for action items and create Legion tasks.
        """
        from app.services.gmail_service import get_gmail_service
        from app.services.legion_client import get_legion_client
        from app.models.email import EmailStatus

        gmail = get_gmail_service()
        legion = get_legion_client()

        # is_connected() is async: `if not gmail.is_connected()` would test a
        # coroutine object, which is always truthy, so the guard would never trip
        # and a disconnected mailbox would fall through to list_emails().
        if not await gmail.is_connected():
            return {"status": "gmail_disconnected", "tasks_created": 0}
        if not await legion.health_check():
            return {"status": "legion_unavailable", "tasks_created": 0}

        # `get_emails(max_results=..., unread_only=...)` no longer exists; the
        # current surface is `list_emails(status=..., limit=...)`.
        emails = await gmail.list_emails(status=EmailStatus.UNREAD, limit=20)
        if not emails:
            return {"status": "no_emails", "tasks_created": 0}

        # Nothing marks these emails read, so every daily run saw the SAME unread
        # inbox, paid for an LLM extraction per message, and re-filed the same
        # action items into a fresh sprint. By 2026-08-06 that had produced three
        # sprints holding 23 tasks, of which "Re-request access to
        # demo@jhu-wd-sandbox.edu" appeared five times and the AI-Interviewer
        # workflow review five more. Remember what has been processed, and never
        # file a title the sprint already carries (Fix-163).
        processed_ids = await self._load_processed_email_ids()
        fresh = [e for e in emails if e.id not in processed_ids]
        if not fresh:
            logger.info("email_to_tasks_all_processed", emails_checked=len(emails))
            return {
                "status": "completed",
                "emails_checked": len(emails),
                "emails_skipped": len(emails),
                "tasks_created": 0,
            }

        tasks_created = 0
        sprint = await self._get_or_create_sprint(
            legion, ZERO_PROJECT_ID, "Plan", "Auto: Email Action Items"
        )
        if not sprint:
            return {"status": "no_sprint", "tasks_created": 0}

        existing_titles = await self._existing_task_titles(legion, sprint["id"])
        newly_processed: List[str] = []
        duplicates_skipped = 0

        for email in fresh:
            if tasks_created >= MAX_TASKS_PER_RUN:
                break

            action_items = await self._extract_action_items(email)
            # Mark processed even with no action items: a second extraction of a
            # message that yielded nothing costs another LLM call for the same
            # nothing.
            newly_processed.append(email.id)
            if not action_items:
                continue

            for item in action_items:
                if tasks_created >= MAX_TASKS_PER_RUN:
                    break
                title = f"[Email] {str(item.get('action', ''))[:100]}"
                # The model paraphrases the same action differently run to run, so
                # the id check alone would not have caught the observed duplicates.
                normalised = " ".join(title.lower().split())
                if normalised in existing_titles:
                    duplicates_skipped += 1
                    continue
                task_data = {
                    "title": title,
                    "description": (
                        f"From: {email.from_address}\n"
                        f"Subject: {email.subject}\n"
                        f"Deadline: {item.get('deadline', 'None detected')}\n"
                        f"Context: {str(item.get('context', ''))[:300]}"
                    ),
                    "priority": item.get("priority", 3),
                    "source": "email_pipeline",
                }
                try:
                    await legion.create_task(sprint["id"], task_data)
                    existing_titles.add(normalised)
                    tasks_created += 1
                except Exception as e:
                    logger.warning("email_task_create_failed", error=str(e))

        await self._save_processed_email_ids(processed_ids, newly_processed)

        logger.info(
            "email_to_tasks",
            emails_checked=len(emails),
            emails_skipped=len(emails) - len(fresh),
            tasks_created=tasks_created,
            duplicates_skipped=duplicates_skipped,
        )
        return {
            "status": "completed",
            "emails_checked": len(emails),
            "emails_skipped": len(emails) - len(fresh),
            "tasks_created": tasks_created,
            "duplicates_skipped": duplicates_skipped,
        }

    # Bound the remembered set: unread mail is a moving window, so an unbounded
    # list would grow forever to answer a question only ever asked about the most
    # recent messages.
    _PROCESSED_EMAIL_MEMORY = 500

    async def _load_processed_email_ids(self) -> set:
        """Email ids already converted to tasks, from ServiceConfigModel."""
        from app.infrastructure.database import get_session
        from app.db.models import ServiceConfigModel

        try:
            async with get_session() as session:
                row = (
                    await session.execute(
                        select(ServiceConfigModel).where(
                            ServiceConfigModel.service_name == "email_to_tasks"
                        )
                    )
                ).scalar_one_or_none()
                if row is None:
                    return set()
                return set((row.config or {}).get("processed_email_ids", []))
        except Exception as e:
            # Degrade to the old re-process behaviour rather than skipping the
            # run: duplicate tasks are recoverable, a silent no-op is not.
            logger.warning("email_processed_ids_load_failed", error=str(e))
            return set()

    async def _save_processed_email_ids(self, previous: set, newly: List[str]) -> None:
        if not newly:
            return
        from app.infrastructure.database import get_session
        from app.db.models import ServiceConfigModel
        from sqlalchemy import update as sa_update

        # Newest last, so the trim below drops the oldest.
        merged = [e for e in previous if e not in set(newly)] + list(newly)
        merged = merged[-self._PROCESSED_EMAIL_MEMORY:]
        try:
            async with get_session() as session:
                row = (
                    await session.execute(
                        select(ServiceConfigModel).where(
                            ServiceConfigModel.service_name == "email_to_tasks"
                        )
                    )
                ).scalar_one_or_none()
                if row is None:
                    session.add(
                        ServiceConfigModel(
                            service_name="email_to_tasks",
                            config={"processed_email_ids": merged},
                        )
                    )
                else:
                    config = dict(row.config or {})
                    config["processed_email_ids"] = merged
                    await session.execute(
                        sa_update(ServiceConfigModel)
                        .where(ServiceConfigModel.service_name == "email_to_tasks")
                        .values(config=config)
                    )
        except Exception as e:
            logger.warning("email_processed_ids_save_failed", error=str(e))

    async def _existing_task_titles(self, legion, sprint_id: Any) -> set:
        """Normalised titles already in the sprint, for duplicate suppression."""
        try:
            tasks = await legion.list_tasks(sprint_id)
        except Exception as e:
            logger.warning("email_existing_titles_failed", error=str(e))
            return set()
        return {
            " ".join(str(t.get("title", "")).lower().split())
            for t in (tasks or [])
            if t.get("title")
        }

    async def _extract_action_items(self, email) -> List[Dict[str, Any]]:
        """
        Extract action items from an email.

        Routed through UnifiedLLMClient. The pre-stub version POSTed directly to
        `http://localhost:11434/api/generate` for `qwen3:32b` -- Ollama, which the
        project retired (`/health/ready` reports `ollama: "retired"`), and which
        `localhost` inside the container could never have reached anyway.
        """
        from app.infrastructure.unified_llm_client import get_unified_llm_client

        subject = email.subject or ""
        body = email.snippet or ""
        from_addr = str(email.from_address) if email.from_address else ""

        prompt = f"""Analyze this email and extract action items. Return a JSON array.
Each item: {{"action": "what to do", "deadline": "date or null", "priority": 1-4, "context": "brief reason"}}

From: {from_addr}
Subject: {subject}
Preview: {body[:500]}

If no action items, return an empty array []. Only return real actionable tasks.
Return ONLY the JSON array, no other text."""

        try:
            items = await get_unified_llm_client().structured_chat(
                prompt=prompt,
                task_type="extraction",
                temperature=0.3,
            )
        except Exception as e:
            logger.debug("action_item_extraction_failed", error=str(e))
            return []

        # structured_chat is typed Union[dict, list] and really does return both
        # shapes for this prompt: a multi-item answer comes back as a list, but a
        # SINGLE action item arrives as a bare object (verified live -- a plainly
        # actionable overdue-invoice email extracted 0 items until this branch
        # existed, because the lone item was a dict and got dropped).
        if isinstance(items, dict):
            for key in ("action_items", "items", "actions", "results", "data"):
                if isinstance(items.get(key), list):
                    items = items[key]
                    break
            else:
                # The object IS the action item, not a wrapper around a list.
                return [items] if "action" in items else []
        if not isinstance(items, list):
            return []
        return [i for i in items if isinstance(i, dict) and i.get("action")]

    # =========================================================================
    # T81: Blocked Task Escalation via Discord
    # =========================================================================

    async def escalate_blocked_tasks(
        self, blocked_threshold_hours: int = 24
    ) -> Dict[str, Any]:
        """
        Escalate tasks blocked longer than the threshold, at most once per day each.

        Distinct from `_run_midday_check`, which posts a digest of everything
        currently blocked at 12:00 with no threshold and no dedup. This is the
        14:00 escalation tier: long-stuck tasks only.
        """
        from app.services.legion_client import get_legion_client
        from app.services.notification_service import get_notification_service
        from app.models.assistant import NotificationChannel

        legion = get_legion_client()
        notification_svc = get_notification_service()

        if not await legion.health_check():
            return {"status": "legion_unavailable", "escalated": 0}

        blocked = await legion.get_blocked_tasks()
        if not blocked:
            return {"status": "no_blocked_tasks", "escalated": 0}

        now = datetime.utcnow()
        escalated = 0

        for task in blocked:
            task_id = task.get("id")
            blocked_since = task.get("started_at") or task.get("created_at")
            if not blocked_since:
                continue

            try:
                if isinstance(blocked_since, str):
                    blocked_dt = datetime.fromisoformat(blocked_since.replace("Z", "+00:00"))
                else:
                    blocked_dt = blocked_since
                hours_blocked = (now - blocked_dt.replace(tzinfo=None)).total_seconds() / 3600
            except Exception:
                hours_blocked = 0

            if hours_blocked < blocked_threshold_hours:
                continue

            last_escalated = self._blocked_task_cache.get(task_id)
            if last_escalated and (now - last_escalated).total_seconds() < 86400:
                continue  # Already escalated in the last 24h

            message = (
                f"**Blocked Task Escalation**\n\n"
                f"Task: **{task.get('title', 'Unknown')}**\n"
                f"Sprint: {task.get('sprint_name', 'N/A')}\n"
                f"Blocked for: {int(hours_blocked)} hours\n"
                f"Error: {str(task.get('last_error') or 'No error recorded')[:200]}\n\n"
                f"Action needed: unblock or reassign this task."
            )

            try:
                await notification_svc.create_notification(
                    title="Blocked Task Alert",
                    message=message,
                    channel=NotificationChannel.DISCORD,
                    source="legion_integration",
                    source_id=str(task_id),
                )
                self._blocked_task_cache[task_id] = now
                escalated += 1
            except Exception as e:
                logger.warning("escalation_failed", task_id=task_id, error=str(e))

        self._prune_escalation_cache(now)

        logger.info("blocked_task_escalation", total_blocked=len(blocked), escalated=escalated)
        return {
            "status": "completed",
            "total_blocked": len(blocked),
            "escalated": escalated,
        }

    def _prune_escalation_cache(self, now: datetime) -> None:
        """Drop cooldown entries that have expired, then hard-cap the remainder."""
        expired = [
            tid for tid, ts in self._blocked_task_cache.items()
            if (now - ts).total_seconds() >= 86400
        ]
        for tid in expired:
            self._blocked_task_cache.pop(tid, None)

        overflow = len(self._blocked_task_cache) - _ESCALATION_CACHE_MAX
        if overflow > 0:
            oldest = sorted(self._blocked_task_cache.items(), key=lambda kv: kv[1])[:overflow]
            for tid, _ in oldest:
                self._blocked_task_cache.pop(tid, None)

    # =========================================================================
    # Helpers
    # =========================================================================

    async def _get_or_create_sprint(
        self, legion, project_id: int, category: str, title: str
    ) -> Optional[Dict]:
        """
        Get the active sprint for a project, or create one for auto-generated tasks.

        Legion enforces a name taxonomy (`^(Fix|Plan|Enhancement|...)-\\d+: <title>$`)
        and auto-allocates the numeric slug, so the payload passes `category` +
        `title` rather than a free-form `name`. The pre-stub version sent
        `{"name": "Auto: ... - <date>"}`, which this gate now rejects with a 422 --
        meaning sprint creation here would have failed even with the import
        repaired. There is no `status` field on SprintCreate either.
        """
        try:
            current = await legion.get_current_sprint(project_id)
            if current:
                return current

            # Reuse an existing OPEN container before opening another one.
            # get_current_sprint only matches status="active", but these
            # containers are filed as "planned" and never started, so that
            # lookup missed on every run and a fresh "<title> - <date>" sprint
            # was created each day. Four had accumulated for project 7 by
            # 2026-08-04, each holding a few pending tasks, with nothing
            # bounding the growth. Match on the title stem so today's tasks
            # land in the container already holding the same kind of work,
            # newest first so the reused row is the most recent one.
            try:
                open_sprints = await legion.list_sprints(
                    project_id=project_id, status="planned", limit=100
                )
            except Exception:
                open_sprints = []
            for sprint in sorted(
                open_sprints or [], key=lambda s: s.get("id") or 0, reverse=True
            ):
                name = sprint.get("name") or ""
                if f": {title} - " in name or name.endswith(f": {title}"):
                    logger.info(
                        "reusing_open_auto_sprint",
                        sprint_id=sprint.get("id"),
                        name=name,
                    )
                    return sprint

            sprint_data = {
                "category": category,
                "title": f"{title} - {datetime.utcnow().strftime('%Y-%m-%d')}",
                "description": f"Auto-created sprint for {title.lower()}",
                "project_id": project_id,
                "priority": 3,
                # Legion v2's governor calibrates on intake provenance; an
                # unattributed filing is recorded as 'v1:unknown'.
                "source_system": "zero_legion_integration",
            }
            return await legion.create_sprint(sprint_data)
        except Exception as e:
            logger.warning(
                "get_or_create_sprint_failed",
                error=str(e),
                project_id=project_id,
                category=category,
            )
            return None

    @staticmethod
    def _severity_to_priority(severity: str) -> int:
        """Map enhancement severity to Legion priority."""
        return {"critical": 1, "high": 2, "medium": 3, "low": 4}.get(severity, 3)


# Singleton
_service: Optional[LegionIntegrationService] = None


def get_legion_integration_service() -> LegionIntegrationService:
    global _service
    if _service is None:
        _service = LegionIntegrationService()
    return _service
