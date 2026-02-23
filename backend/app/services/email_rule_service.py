"""
Email rule service for user-defined email automation rules.

Provides CRUD operations, rule evaluation engine, and action execution
including LLM-based date extraction for calendar event creation.
"""

import json
import re
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict, Any

import structlog
from sqlalchemy import select, update, delete
from sqlalchemy.orm import Session

from app.db.models import EmailRuleModel
from app.infrastructure.database import get_session
from app.models.email_rule import (
    EmailRule,
    EmailRuleCreate,
    EmailRuleUpdate,
    RuleCondition,
    ConditionsBlock,
    RuleAction,
    RuleTestResult,
    RuleTestRequest,
    ConditionField,
    ConditionOperator,
    ActionType,
)

logger = structlog.get_logger()


class EmailRuleService:
    """Service for email rule management and evaluation."""

    # -----------------------------------------------------------------------
    # CRUD
    # -----------------------------------------------------------------------

    async def list_rules(self, enabled_only: bool = False) -> List[EmailRule]:
        """Get all rules ordered by priority (lower first)."""
        async with get_session() as session:
            stmt = select(EmailRuleModel).order_by(EmailRuleModel.priority)
            if enabled_only:
                stmt = stmt.where(EmailRuleModel.enabled == True)  # noqa: E712
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [self._to_pydantic(r) for r in rows]

    async def get_rule(self, rule_id: str) -> Optional[EmailRule]:
        """Get a single rule by ID."""
        async with get_session() as session:
            row = await session.get(EmailRuleModel, rule_id)
            return self._to_pydantic(row) if row else None

    async def create_rule(self, data: EmailRuleCreate) -> EmailRule:
        """Create a new email rule."""
        rule_id = f"rule-{uuid.uuid4().hex[:12]}"
        async with get_session() as session:
            row = EmailRuleModel(
                id=rule_id,
                name=data.name,
                description=data.description,
                enabled=data.enabled,
                priority=data.priority,
                stop_after_match=data.stop_after_match,
                conditions=data.conditions.model_dump(),
                actions=[a.model_dump() for a in data.actions],
                match_count=0,
            )
            session.add(row)
            await session.flush()
            logger.info("email_rule_created", rule_id=rule_id, name=data.name)
            return self._to_pydantic(row)

    async def update_rule(self, rule_id: str, data: EmailRuleUpdate) -> Optional[EmailRule]:
        """Update an existing rule (partial update)."""
        async with get_session() as session:
            row = await session.get(EmailRuleModel, rule_id)
            if not row:
                return None
            if data.name is not None:
                row.name = data.name
            if data.description is not None:
                row.description = data.description
            if data.enabled is not None:
                row.enabled = data.enabled
            if data.priority is not None:
                row.priority = data.priority
            if data.stop_after_match is not None:
                row.stop_after_match = data.stop_after_match
            if data.conditions is not None:
                row.conditions = data.conditions.model_dump()
            if data.actions is not None:
                row.actions = [a.model_dump() for a in data.actions]
            await session.flush()
            logger.info("email_rule_updated", rule_id=rule_id)
            return self._to_pydantic(row)

    async def delete_rule(self, rule_id: str) -> bool:
        """Delete a rule."""
        async with get_session() as session:
            result = await session.execute(
                delete(EmailRuleModel).where(EmailRuleModel.id == rule_id)
            )
            deleted = result.rowcount > 0
            if deleted:
                logger.info("email_rule_deleted", rule_id=rule_id)
            return deleted

    async def toggle_rule(self, rule_id: str, enabled: bool) -> Optional[EmailRule]:
        """Enable or disable a rule."""
        return await self.update_rule(rule_id, EmailRuleUpdate(enabled=enabled))

    # -----------------------------------------------------------------------
    # LLM Rule Generation
    # -----------------------------------------------------------------------

    async def generate_rule_from_prompt(self, prompt: str) -> EmailRuleCreate:
        """Use LLM to generate an EmailRuleCreate from a natural language description."""
        from app.infrastructure.ollama_client import get_ollama_client

        client = get_ollama_client()
        raw = await client.chat(
            prompt=f"{prompt}\n\n/no_think",
            system=self._get_rule_generation_system_prompt(),
            task_type="workflow",
            temperature=0.1,
            num_predict=1024,
            timeout=30,
        )

        if not raw.strip():
            raise ValueError("LLM returned empty response")

        parsed = self._parse_nested_json_from_llm(raw)
        if not parsed:
            raise ValueError(f"Could not parse JSON from LLM response: {raw[:300]}")

        try:
            rule = EmailRuleCreate(**parsed)
        except Exception as e:
            raise ValueError(f"LLM output failed validation: {e}")

        return rule

    def _get_rule_generation_system_prompt(self) -> str:
        return """You are an email rule generator. Convert the user's natural language description into a structured JSON email rule.

RESPOND WITH ONLY A SINGLE JSON OBJECT. No explanation, no markdown, no extra text.

The JSON must have this exact structure:
{
  "name": "Short rule name",
  "description": "What this rule does",
  "enabled": true,
  "priority": 100,
  "stop_after_match": false,
  "conditions": {
    "match_mode": "all" or "any",
    "conditions": [
      {
        "field": "<field>",
        "operator": "<operator>",
        "value": "<value>",
        "case_sensitive": false
      }
    ]
  },
  "actions": [
    {
      "type": "<action_type>",
      "params": {}
    }
  ]
}

AVAILABLE CONDITION FIELDS:
- "sender" - the sender's email address
- "subject" - the email subject line
- "body" - the email body text
- "category" - email category
- "has_attachments" - whether email has attachments (use value: true, operator: "exact")
- "label" - Gmail label

AVAILABLE CONDITION OPERATORS:
- "contains" - field contains the value (most common, use by default)
- "not_contains" - field does not contain the value
- "exact" - field exactly matches value
- "regex" - regular expression match
- "starts_with" - field starts with value
- "ends_with" - field ends with value

AVAILABLE ACTION TYPES:
- "archive" - archive the email (params: {})
- "star" - star the email (params: {})
- "mark_read" - mark as read (params: {})
- "apply_label" - apply a Gmail label (params: {"label": "LabelName"})
- "notify" - send a notification (params: {"title": "notification title"})
- "create_calendar_event" - extract dates and create calendar event (params: {"event_prefix": "", "default_duration_minutes": 30})
- "create_task" - create a task from the email (params: {"title_prefix": "[Email] ", "priority": "medium", "category": "chore"})

RULES:
1. For "emails from X" use field "sender" with operator "contains"
2. For "emails about X" use field "subject" with operator "contains"
3. For domain matching like "from gmail.com" use "sender" with "ends_with" and value "@gmail.com"
4. Use match_mode "any" when the user says "or", otherwise use "all"
5. Pick the most appropriate action from the user's intent
6. For apply_label, infer a sensible label name from context
7. For create_task, set priority based on urgency words (urgent/asap = "high", important = "medium")
8. Generate a concise, descriptive name for the rule
9. Set priority to 100 unless the user indicates importance"""

    def _parse_nested_json_from_llm(self, text: str) -> Optional[dict]:
        """Extract a nested JSON object from LLM response text."""
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Strip markdown code fences
        if "```" in text:
            match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1).strip())
                except json.JSONDecodeError:
                    pass
        # Find outermost { ... } with balanced braces
        start = text.find('{')
        if start != -1:
            depth = 0
            for i in range(start, len(text)):
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i + 1])
                        except json.JSONDecodeError:
                            break
        return None

    # -----------------------------------------------------------------------
    # Evaluation Engine
    # -----------------------------------------------------------------------

    async def evaluate_rules(self, email_data: dict) -> List[EmailRule]:
        """Evaluate all enabled rules against an email. Returns matched rules in priority order."""
        rules = await self.list_rules(enabled_only=True)
        matched = []
        for rule in rules:
            if self._evaluate_conditions(rule.conditions, email_data):
                matched.append(rule)
                if rule.stop_after_match:
                    break
        return matched

    def _evaluate_conditions(self, block: ConditionsBlock, email_data: dict) -> bool:
        """Evaluate a conditions block against email data."""
        results = [self._evaluate_condition(c, email_data) for c in block.conditions]
        if block.match_mode == "any":
            return any(results)
        return all(results)

    def _evaluate_condition(self, condition: RuleCondition, email_data: dict) -> bool:
        """Evaluate a single condition against email data."""
        field = condition.field
        operator = condition.operator
        expected = condition.value
        case_sensitive = condition.case_sensitive

        # Extract the actual value from email data
        if field == ConditionField.SENDER:
            actual = email_data.get("from_address", {})
            if isinstance(actual, dict):
                actual = actual.get("email", "")
            else:
                actual = str(actual)
        elif field == ConditionField.SUBJECT:
            actual = email_data.get("subject", "")
        elif field == ConditionField.BODY:
            actual = email_data.get("body_text", "") or email_data.get("snippet", "")
        elif field == ConditionField.CATEGORY:
            actual = email_data.get("category", "normal")
        elif field == ConditionField.HAS_ATTACHMENTS:
            attachments = email_data.get("attachments", [])
            has = len(attachments) > 0 if attachments else False
            return has == bool(expected)
        elif field == ConditionField.LABEL:
            labels = email_data.get("labels", [])
            if isinstance(expected, list):
                return any(lbl in labels for lbl in expected)
            return str(expected) in labels
        else:
            return False

        # For string fields, handle matching
        if isinstance(expected, list):
            return any(self._match_value(actual, operator, v, case_sensitive) for v in expected)
        return self._match_value(actual, operator, str(expected), case_sensitive)

    def _match_value(self, actual: str, operator: ConditionOperator, expected: str, case_sensitive: bool) -> bool:
        """Core string matching."""
        if not case_sensitive:
            actual = actual.lower()
            expected = expected.lower()

        if operator == ConditionOperator.CONTAINS:
            return expected in actual
        elif operator == ConditionOperator.NOT_CONTAINS:
            return expected not in actual
        elif operator == ConditionOperator.EXACT:
            return actual == expected
        elif operator == ConditionOperator.STARTS_WITH:
            return actual.startswith(expected)
        elif operator == ConditionOperator.ENDS_WITH:
            return actual.endswith(expected)
        elif operator == ConditionOperator.REGEX:
            try:
                flags = 0 if case_sensitive else re.IGNORECASE
                return bool(re.search(expected, actual, flags))
            except re.error:
                logger.warning("invalid_regex_in_rule", pattern=expected)
                return False
        return False

    # -----------------------------------------------------------------------
    # Action Execution
    # -----------------------------------------------------------------------

    async def execute_actions(self, rule: EmailRule, email_id: str, email_data: dict) -> List[dict]:
        """Execute all actions for a matched rule. Returns list of action results."""
        results = []
        for action in rule.actions:
            try:
                result = await self._execute_action(action, email_id, email_data)
                results.append({"action": action.type, "status": "success", **result})
            except Exception as e:
                logger.error(
                    "rule_action_failed",
                    rule_id=rule.id,
                    action=action.type,
                    error=str(e),
                )
                results.append({"action": action.type, "status": "error", "error": str(e)})

        # Update match stats
        await self._increment_match_count(rule.id)
        return results

    async def _execute_action(self, action: RuleAction, email_id: str, email_data: dict) -> dict:
        """Dispatch a single action."""
        t = action.type
        params = action.params

        if t == ActionType.ARCHIVE:
            return await self._execute_archive(email_id)
        elif t == ActionType.STAR:
            return await self._execute_star(email_id)
        elif t == ActionType.MARK_READ:
            return await self._execute_mark_read(email_id)
        elif t == ActionType.APPLY_LABEL:
            return await self._execute_apply_label(email_id, params)
        elif t == ActionType.NOTIFY:
            return await self._execute_notify(email_data, params)
        elif t == ActionType.CREATE_CALENDAR_EVENT:
            return await self._execute_create_calendar_event(email_data, params)
        elif t == ActionType.CREATE_TASK:
            return await self._execute_create_task(email_data, params)
        else:
            return {"message": f"Unknown action type: {t}"}

    async def _execute_archive(self, email_id: str) -> dict:
        from app.services.gmail_service import get_gmail_service
        await get_gmail_service().archive_email(email_id)
        return {"message": "Email archived"}

    async def _execute_star(self, email_id: str) -> dict:
        from app.services.gmail_service import get_gmail_service
        await get_gmail_service().star_email(email_id, starred=True)
        return {"message": "Email starred"}

    async def _execute_mark_read(self, email_id: str) -> dict:
        from app.services.gmail_service import get_gmail_service
        await get_gmail_service().mark_as_read(email_id)
        return {"message": "Email marked as read"}

    async def _execute_apply_label(self, email_id: str, params: dict) -> dict:
        label = params.get("label", "")
        if not label:
            return {"message": "No label specified"}
        from app.services.gmail_service import get_gmail_service
        gmail = get_gmail_service()
        # Gmail API: modify labels
        try:
            service = gmail._get_service()
            service.users().messages().modify(
                userId="me",
                id=email_id,
                body={"addLabelIds": [label]}
            ).execute()
            return {"message": f"Label '{label}' applied"}
        except Exception as e:
            return {"message": f"Failed to apply label: {e}"}

    async def _execute_notify(self, email_data: dict, params: dict) -> dict:
        from app.services.notification_service import get_notification_service
        title = params.get("title", f"Email Rule: {email_data.get('subject', '(No Subject)')[:80]}")
        message = f"From: {email_data.get('from_address', {}).get('email', 'unknown')}\n{email_data.get('snippet', '')[:200]}"
        await get_notification_service().create_notification(
            title=title,
            message=message,
            source="email_rule",
            source_id=email_data.get("id"),
        )
        return {"message": "Notification created"}

    async def _execute_create_calendar_event(self, email_data: dict, params: dict) -> dict:
        """Extract event info from email via LLM and create a calendar event."""
        from app.infrastructure.ollama_client import get_ollama_client
        from app.services.calendar_service import get_calendar_service
        from app.models.calendar import EventCreate, EventDateTime

        subject = email_data.get("subject", "")
        body = email_data.get("body_text", "") or email_data.get("snippet", "")
        sender = email_data.get("from_address", {}).get("email", "")
        today = datetime.utcnow().strftime("%Y-%m-%d")

        prompt = (
            f"Extract event/appointment/due-date details from this email. "
            f"Today is {today}.\n\n"
            f"From: {sender}\n"
            f"Subject: {subject}\n"
            f"Body: {body[:1500]}\n\n"
            f"If this contains a bill due date, appointment, meeting, or deadline, extract:\n"
            f'- title: short event title\n'
            f'- date: YYYY-MM-DD format\n'
            f'- time: HH:MM 24h format, or null if all-day\n'
            f'- duration_minutes: estimated duration (default 30)\n'
            f'- location: if mentioned, else null\n\n'
            f'Respond ONLY with JSON: {{"title":"...","date":"...","time":"...","duration_minutes":N,"location":"..."}}\n'
            f'If no date found, respond: {{"title":null}}\n/no_think'
        )

        content = await get_ollama_client().chat_safe(
            prompt, task_type="analysis", temperature=0.1, num_predict=300
        )

        if not content:
            return {"message": "LLM returned empty response, skipping calendar event"}

        # Parse JSON from LLM response
        event_info = self._parse_json_from_llm(content)
        if not event_info or not event_info.get("title") or not event_info.get("date"):
            return {"message": "Could not extract event date from email", "llm_response": content[:200]}

        # Build EventCreate
        event_prefix = params.get("event_prefix", "")
        duration = event_info.get("duration_minutes", params.get("default_duration_minutes", 30))
        summary = f"{event_prefix}{event_info['title']}"

        try:
            if event_info.get("time"):
                start_dt = datetime.fromisoformat(f"{event_info['date']}T{event_info['time']}:00")
                end_dt = start_dt + timedelta(minutes=int(duration))
                start = EventDateTime(date_time=start_dt, timezone="America/New_York")
                end = EventDateTime(date_time=end_dt, timezone="America/New_York")
            else:
                # All-day event
                start = EventDateTime(date=event_info["date"])
                end = EventDateTime(date=event_info["date"])

            event_data = EventCreate(
                summary=summary,
                description=f"Auto-created from email\nFrom: {sender}\nSubject: {subject}",
                location=event_info.get("location"),
                start=start,
                end=end,
            )

            calendar = get_calendar_service()
            event = await calendar.create_event(event_data)
            return {"message": "Calendar event created", "event_id": event.id, "summary": summary}
        except Exception as e:
            logger.error("calendar_event_creation_failed", error=str(e))
            return {"message": f"Failed to create calendar event: {e}"}

    async def _execute_create_task(self, email_data: dict, params: dict) -> dict:
        """Create a Zero task from email."""
        from app.services.task_service import get_task_service
        from app.models.task import TaskCreate, TaskCategory, TaskPriority, TaskSource

        subject = email_data.get("subject", "(No Subject)")
        sender = email_data.get("from_address", {}).get("email", "")
        snippet = email_data.get("snippet", "")
        prefix = params.get("title_prefix", "[Email] ")
        priority = params.get("priority", "medium")
        category = params.get("category", "chore")

        task_data = TaskCreate(
            title=f"{prefix}{subject}",
            description=f"From: {sender}\n\n{snippet}\n\n---\nEmail ID: {email_data.get('id', '')}",
            sprint_id=params.get("sprint_id"),
            project_id=params.get("project_id"),
            category=TaskCategory(category),
            priority=TaskPriority(priority),
            source=TaskSource.MANUAL,
            source_reference=f"email:{email_data.get('id', '')}",
        )

        task = await get_task_service().create_task(task_data)
        return {"message": "Task created", "task_id": task.id, "task_title": task.title}

    # -----------------------------------------------------------------------
    # Testing (dry run)
    # -----------------------------------------------------------------------

    async def test_rule(self, request: RuleTestRequest) -> RuleTestResult:
        """Test a rule against an email without executing actions."""
        from app.services.gmail_service import get_gmail_service

        email = await get_gmail_service().get_email(request.email_id)
        if not email:
            raise ValueError(f"Email {request.email_id} not found")

        email_data = email.model_dump()

        # Get the rule to test
        if request.rule:
            conditions = request.rule.conditions
            actions = request.rule.actions
        elif request.rule_id:
            rule = await self.get_rule(request.rule_id)
            if not rule:
                raise ValueError(f"Rule {request.rule_id} not found")
            conditions = rule.conditions
            actions = rule.actions
        else:
            raise ValueError("Either rule or rule_id must be provided")

        # Evaluate each condition individually
        conditions_evaluated = []
        for c in conditions.conditions:
            matched = self._evaluate_condition(c, email_data)
            conditions_evaluated.append({
                "field": c.field,
                "operator": c.operator,
                "value": c.value,
                "matched": matched,
            })

        overall_match = self._evaluate_conditions(conditions, email_data)

        return RuleTestResult(
            matched=overall_match,
            conditions_evaluated=conditions_evaluated,
            actions_that_would_execute=actions if overall_match else [],
            email_subject=email_data.get("subject", ""),
            email_from=email_data.get("from_address", {}).get("email", ""),
        )

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    async def _increment_match_count(self, rule_id: str):
        """Increment match count and update last_matched_at."""
        try:
            async with get_session() as session:
                await session.execute(
                    update(EmailRuleModel)
                    .where(EmailRuleModel.id == rule_id)
                    .values(
                        match_count=EmailRuleModel.match_count + 1,
                        last_matched_at=datetime.utcnow(),
                    )
                )
        except Exception as e:
            logger.error("failed_to_update_match_count", rule_id=rule_id, error=str(e))

    def _to_pydantic(self, row: EmailRuleModel) -> EmailRule:
        """Convert DB row to Pydantic model."""
        return EmailRule(
            id=row.id,
            name=row.name,
            description=row.description,
            enabled=row.enabled,
            priority=row.priority,
            stop_after_match=row.stop_after_match,
            conditions=ConditionsBlock(**row.conditions),
            actions=[RuleAction(**a) for a in row.actions],
            match_count=row.match_count,
            last_matched_at=row.last_matched_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _parse_json_from_llm(self, text: str) -> Optional[dict]:
        """Extract JSON object from LLM response text."""
        # Try direct parse first
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try to find JSON in response
        match = re.search(r'\{[^{}]*\}', text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return None


def get_email_rule_service() -> EmailRuleService:
    """Get EmailRuleService instance."""
    return EmailRuleService()
