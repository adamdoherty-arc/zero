"""
Gmail service for email operations.

Persistence layer uses PostgreSQL via SQLAlchemy async ORM.
"""

import json
import base64
from pathlib import Path
from typing import Optional, List, Dict, Any
from functools import lru_cache
from datetime import datetime, timedelta
import structlog

from sqlalchemy import select, update, func as sa_func

from app.models.email import (
    Email, EmailSummary, EmailThread, EmailLabel,
    EmailCategory, EmailStatus, EmailAddress, EmailAttachment,
    EmailSyncStatus, EmailDigest
)
from app.services.gmail_oauth_service import get_gmail_oauth_service
from app.infrastructure.database import get_session
from app.infrastructure.circuit_breaker import get_circuit_breaker
from app.db.models import EmailCacheModel, SyncStatusModel

logger = structlog.get_logger()


class GmailService:
    """Service for Gmail operations."""

    def __init__(self, workspace_path: str = "workspace"):
        self.workspace_path = Path(workspace_path)
        self.email_path = self.workspace_path / "email"
        self.email_path.mkdir(parents=True, exist_ok=True)
        self._service = None
        self._breaker = get_circuit_breaker(
            "gmail",
            failure_threshold=3,
            recovery_timeout=60.0,
        )

    async def is_connected(self) -> bool:
        """Check if Gmail is configured and connected."""
        status = await self._load_sync_status()
        return status.connected if hasattr(status, 'connected') else False

    def _get_gmail_service(self):
        """Get authenticated Gmail API service."""
        if self._service:
            return self._service

        oauth_service = get_gmail_oauth_service()
        creds = oauth_service.get_credentials()

        if not creds:
            raise RuntimeError("Gmail not connected. Complete OAuth flow first.")

        try:
            from googleapiclient.discovery import build
            self._service = build("gmail", "v1", credentials=creds)
            return self._service
        except ImportError:
            raise RuntimeError(
                "Google API client not installed. "
                "Install with: pip install google-api-python-client"
            )

    # ------------------------------------------------------------------
    # Sync Status (PostgreSQL)
    # ------------------------------------------------------------------

    async def _load_sync_status(self) -> EmailSyncStatus:
        """Load sync status from PostgreSQL."""
        try:
            async with get_session() as session:
                row = await session.get(SyncStatusModel, "gmail")
                if row:
                    return EmailSyncStatus(
                        connected=row.connected,
                        email_address=row.email_address,
                        last_sync=row.last_sync,
                        total_messages=(row.metadata_ or {}).get("total_messages", 0),
                        unread_count=(row.metadata_ or {}).get("unread_count", 0),
                        sync_errors=row.errors or [],
                    )
        except Exception:
            pass
        return EmailSyncStatus()

    async def _save_sync_status(self, status: EmailSyncStatus) -> None:
        """Save sync status to PostgreSQL."""
        async with get_session() as session:
            await session.merge(SyncStatusModel(
                service_name="gmail",
                connected=status.connected,
                email_address=status.email_address,
                last_sync=status.last_sync,
                metadata_={
                    "total_messages": status.total_messages,
                    "unread_count": status.unread_count,
                },
                errors=status.sync_errors or [],
            ))

    async def get_sync_status(self) -> EmailSyncStatus:
        """Get current sync status."""
        oauth_service = get_gmail_oauth_service()
        status = await self._load_sync_status()
        status.connected = oauth_service.has_valid_tokens()
        return status

    # ------------------------------------------------------------------
    # Email parsing helpers (unchanged)
    # ------------------------------------------------------------------

    def _parse_email_address(self, raw: str) -> EmailAddress:
        """Parse email address string into EmailAddress."""
        import re
        # Match "Name <email>" or just "email"
        match = re.match(r'^(?:"?([^"<]+)"?\s*)?<?([^>]+)>?$', raw.strip())
        if match:
            name = match.group(1)
            email = match.group(2)
            return EmailAddress(email=email.strip(), name=name.strip() if name else None)
        return EmailAddress(email=raw.strip())

    def _parse_headers(self, headers: List[Dict]) -> Dict[str, str]:
        """Parse message headers into dict."""
        return {h["name"].lower(): h["value"] for h in headers}

    def _decode_body(self, payload: Dict) -> tuple[Optional[str], Optional[str]]:
        """Decode message body (text and HTML)."""
        text_body = None
        html_body = None

        def extract_parts(part: Dict):
            nonlocal text_body, html_body
            mime_type = part.get("mimeType", "")
            body = part.get("body", {})

            if body.get("data"):
                data = base64.urlsafe_b64decode(body["data"]).decode("utf-8", errors="ignore")
                if mime_type == "text/plain" and not text_body:
                    text_body = data
                elif mime_type == "text/html" and not html_body:
                    html_body = data

            for sub_part in part.get("parts", []):
                extract_parts(sub_part)

        extract_parts(payload)
        return text_body, html_body

    def _classify_email(self, email: Dict, headers: Dict) -> EmailCategory:
        """Classify email into category using rules + optional AI classification."""
        labels = email.get("labelIds", [])
        subject = headers.get("subject", "").lower()
        from_addr = headers.get("from", "").lower()

        # Fast path: Gmail labels are definitive
        if "SPAM" in labels:
            return EmailCategory.SPAM
        if "IMPORTANT" in labels or "STARRED" in labels:
            return EmailCategory.IMPORTANT

        # Keyword-based rules (fast, no LLM needed)
        urgent_keywords = ["urgent", "asap", "emergency", "critical", "immediate"]
        if any(kw in subject for kw in urgent_keywords):
            return EmailCategory.URGENT

        newsletter_indicators = [
            "unsubscribe", "newsletter", "noreply", "no-reply",
            "digest", "weekly", "daily update"
        ]
        if any(ind in subject or ind in from_addr for ind in newsletter_indicators):
            return EmailCategory.NEWSLETTER

        return EmailCategory.NORMAL

    async def classify_email_ai(self, subject: str, from_addr: str, body_preview: str) -> EmailCategory:
        """Classify email using Ollama LLM for better accuracy."""
        import httpx

        prompt = f"""Classify this email into exactly one category.

Categories: URGENT, IMPORTANT, NORMAL, LOW_PRIORITY, NEWSLETTER, SPAM

Email:
- From: {from_addr}
- Subject: {subject}
- Body preview: {body_preview[:300]}

Reply with ONLY the category name, nothing else."""

        try:
            from app.infrastructure.ollama_client import get_ollama_client
            result = await get_ollama_client().chat_safe(
                prompt, task_type="classification", num_predict=20, temperature=0.1, timeout=60,
            )
            if result:
                result_upper = result.strip().upper()
                for cat in EmailCategory:
                    if cat.value.upper() in result_upper:
                        return cat
        except Exception as e:
            logger.debug("ai_classification_fallback", error=str(e))

        return EmailCategory.NORMAL

    # ------------------------------------------------------------------
    # Helper: build Email pydantic model from ORM row
    # ------------------------------------------------------------------

    def _row_to_email(self, row: EmailCacheModel) -> Email:
        """Convert an EmailCacheModel ORM row to an Email pydantic model."""
        from_addr = EmailAddress(**(row.from_address or {"email": "unknown"}))
        to_addrs = [EmailAddress(**a) for a in (row.to_addresses or [])]
        cc_addrs = [EmailAddress(**a) for a in (row.cc_addresses or [])]
        attachments = [EmailAttachment(**a) for a in (row.attachments or [])]

        return Email(
            id=row.id,
            thread_id=row.thread_id or row.id,
            subject=row.subject or "(No Subject)",
            snippet=row.snippet or "",
            body_text=row.body_text,
            body_html=None,  # not stored in DB
            from_address=from_addr,
            to_addresses=to_addrs,
            cc_addresses=cc_addrs,
            labels=row.labels or [],
            attachments=attachments,
            category=EmailCategory(row.category) if row.category else EmailCategory.NORMAL,
            status=EmailStatus(row.status) if row.status else EmailStatus.UNREAD,
            is_starred=row.is_starred or False,
            is_important=row.is_important or False,
            received_at=row.received_at or datetime.utcnow(),
            internal_date=row.internal_date or 0,
            synced_at=row.synced_at or datetime.utcnow(),
        )

    def _row_to_summary(self, row: EmailCacheModel) -> EmailSummary:
        """Convert an EmailCacheModel ORM row to an EmailSummary."""
        from_addr = EmailAddress(**(row.from_address or {"email": "unknown"}))
        return EmailSummary(
            id=row.id,
            thread_id=row.thread_id or row.id,
            subject=row.subject or "(No Subject)",
            snippet=row.snippet or "",
            from_address=from_addr,
            category=EmailCategory(row.category) if row.category else EmailCategory.NORMAL,
            status=EmailStatus(row.status) if row.status else EmailStatus.UNREAD,
            is_starred=row.is_starred or False,
            is_important=row.is_important or False,
            has_attachments=bool(row.attachments),
            received_at=row.received_at or datetime.utcnow(),
        )

    # ------------------------------------------------------------------
    # Helper: build an ORM row from a parsed Gmail API message
    # ------------------------------------------------------------------

    def _email_to_row(self, email: Email) -> EmailCacheModel:
        """Convert an Email pydantic model to an EmailCacheModel ORM row."""
        return EmailCacheModel(
            id=email.id,
            thread_id=email.thread_id,
            subject=email.subject,
            snippet=email.snippet,
            body_text=email.body_text,
            from_address=email.from_address.model_dump(),
            to_addresses=[a.model_dump() for a in email.to_addresses],
            cc_addresses=[a.model_dump() for a in email.cc_addresses],
            labels=email.labels,
            attachments=[a.model_dump() for a in email.attachments],
            category=email.category.value,
            status=email.status.value,
            is_starred=email.is_starred,
            is_important=email.is_important,
            received_at=email.received_at,
            internal_date=email.internal_date,
            synced_at=email.synced_at,
        )

    # ------------------------------------------------------------------
    # Core operations (PostgreSQL persistence)
    # ------------------------------------------------------------------

    async def sync_inbox(
        self,
        max_results: int = 100,
        days_back: int = 7
    ) -> Dict[str, Any]:
        """
        Sync inbox from Gmail.

        Args:
            max_results: Maximum emails to fetch
            days_back: Fetch emails from this many days back

        Returns:
            Sync result with counts
        """
        service = self._get_gmail_service()
        status = await self._load_sync_status()

        # Build query for recent emails
        after_date = datetime.utcnow() - timedelta(days=days_back)
        query = f"after:{after_date.strftime('%Y/%m/%d')}"

        try:
            # Get message list (through circuit breaker)
            async def _list_messages():
                return service.users().messages().list(
                    userId="me",
                    q=query,
                    maxResults=max_results
                ).execute()

            results = await self._breaker.call(_list_messages)

            messages = results.get("messages", [])
            emails = []
            errors = []

            for msg_ref in messages:
                try:
                    # Fetch full message
                    msg = service.users().messages().get(
                        userId="me",
                        id=msg_ref["id"],
                        format="full"
                    ).execute()

                    headers = self._parse_headers(msg.get("payload", {}).get("headers", []))
                    text_body, html_body = self._decode_body(msg.get("payload", {}))

                    # Parse addresses
                    from_addr = self._parse_email_address(headers.get("from", ""))
                    to_addrs = [
                        self._parse_email_address(a.strip())
                        for a in headers.get("to", "").split(",") if a.strip()
                    ]
                    cc_addrs = [
                        self._parse_email_address(a.strip())
                        for a in headers.get("cc", "").split(",") if a.strip()
                    ]

                    # Parse attachments
                    attachments = []
                    for part in msg.get("payload", {}).get("parts", []):
                        if part.get("filename"):
                            attachments.append(EmailAttachment(
                                filename=part["filename"],
                                mime_type=part.get("mimeType", "application/octet-stream"),
                                size_bytes=int(part.get("body", {}).get("size", 0)),
                                attachment_id=part.get("body", {}).get("attachmentId")
                            ))

                    # Classify
                    category = self._classify_email(msg, headers)

                    # Build email object
                    email = Email(
                        id=msg["id"],
                        thread_id=msg.get("threadId", msg["id"]),
                        subject=headers.get("subject", "(No Subject)"),
                        snippet=msg.get("snippet", ""),
                        body_text=text_body,
                        body_html=html_body,
                        from_address=from_addr,
                        to_addresses=to_addrs,
                        cc_addresses=cc_addrs,
                        labels=msg.get("labelIds", []),
                        attachments=attachments,
                        category=category,
                        status=EmailStatus.UNREAD if "UNREAD" in msg.get("labelIds", []) else EmailStatus.READ,
                        is_starred="STARRED" in msg.get("labelIds", []),
                        is_important="IMPORTANT" in msg.get("labelIds", []),
                        received_at=datetime.fromtimestamp(int(msg.get("internalDate", 0)) / 1000),
                        internal_date=int(msg.get("internalDate", 0)),
                        synced_at=datetime.utcnow()
                    )
                    emails.append(email)

                except Exception as e:
                    errors.append(f"Error fetching {msg_ref['id']}: {str(e)}")
                    logger.warning("gmail_message_fetch_error", id=msg_ref["id"], error=str(e))

            # Upsert all emails into PostgreSQL
            async with get_session() as session:
                for email in emails:
                    await session.merge(self._email_to_row(email))

            # Get profile for email address
            async def _get_profile():
                return service.users().getProfile(userId="me").execute()

            profile = await self._breaker.call(_get_profile)

            # Update sync status
            unread = len([e for e in emails if e.status == EmailStatus.UNREAD])
            sync_status = EmailSyncStatus(
                connected=True,
                email_address=profile.get("emailAddress"),
                last_sync=datetime.utcnow(),
                total_messages=len(emails),
                unread_count=unread,
                sync_errors=errors
            )
            await self._save_sync_status(sync_status)

            # Store history_id for incremental sync
            history_id = results.get("historyId") or (
                service.users().getProfile(userId="me").execute().get("historyId")
                if not results.get("historyId") else None
            )
            if history_id:
                async with get_session() as session:
                    row = await session.get(SyncStatusModel, "gmail")
                    if row:
                        meta = row.metadata_ or {}
                        meta["history_id"] = str(history_id)
                        row.metadata_ = meta
                        await session.merge(row)

            logger.info(
                "gmail_sync_complete",
                total=len(emails),
                unread=unread,
                errors=len(errors)
            )

            return {
                "status": "success",
                "synced_at": datetime.utcnow().isoformat(),
                "total_messages": len(emails),
                "unread_count": unread,
                "errors": errors
            }

        except Exception as e:
            logger.error("gmail_sync_failed", error=str(e))
            status.sync_errors.append(str(e))
            await self._save_sync_status(status)
            raise

    async def list_emails(
        self,
        category: Optional[EmailCategory] = None,
        status: Optional[EmailStatus] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[EmailSummary]:
        """List emails from DB with optional filters."""
        async with get_session() as session:
            stmt = select(EmailCacheModel)

            if category:
                stmt = stmt.where(EmailCacheModel.category == category.value)
            if status:
                stmt = stmt.where(EmailCacheModel.status == status.value)

            stmt = stmt.order_by(EmailCacheModel.received_at.desc())
            stmt = stmt.offset(offset).limit(limit)

            result = await session.execute(stmt)
            rows = result.scalars().all()

        return [self._row_to_summary(row) for row in rows]

    async def get_email(self, email_id: str) -> Optional[Email]:
        """Get full email by ID."""
        async with get_session() as session:
            row = await session.get(EmailCacheModel, email_id)
            if row:
                return self._row_to_email(row)
        return None

    async def get_labels(self) -> List[EmailLabel]:
        """Get Gmail labels."""
        service = self._get_gmail_service()

        async def _fetch_labels():
            results = service.users().labels().list(userId="me").execute()
            labels = []

            for label in results.get("labels", []):
                # Get label details
                label_detail = service.users().labels().get(
                    userId="me",
                    id=label["id"]
                ).execute()

                labels.append(EmailLabel(
                    id=label["id"],
                    name=label["name"],
                    type=label.get("type", "user"),
                    message_count=label_detail.get("messagesTotal", 0),
                    unread_count=label_detail.get("messagesUnread", 0)
                ))

            return labels

        return await self._breaker.call(_fetch_labels)

    async def mark_as_read(self, email_id: str) -> bool:
        """Mark email as read."""
        try:
            service = self._get_gmail_service()

            async def _mark_read():
                service.users().messages().modify(
                    userId="me",
                    id=email_id,
                    body={"removeLabelIds": ["UNREAD"]}
                ).execute()

            await self._breaker.call(_mark_read)

            # Update DB
            async with get_session() as session:
                row = await session.get(EmailCacheModel, email_id)
                if row:
                    row.status = EmailStatus.READ.value
                    labels = list(row.labels or [])
                    if "UNREAD" in labels:
                        labels.remove("UNREAD")
                    row.labels = labels

            return True
        except Exception as e:
            logger.error("mark_as_read_failed", email_id=email_id, error=str(e))
            return False

    async def archive_email(self, email_id: str) -> bool:
        """Archive email (remove from inbox)."""
        try:
            service = self._get_gmail_service()

            async def _archive():
                service.users().messages().modify(
                    userId="me",
                    id=email_id,
                    body={"removeLabelIds": ["INBOX"]}
                ).execute()

            await self._breaker.call(_archive)

            # Update DB
            async with get_session() as session:
                row = await session.get(EmailCacheModel, email_id)
                if row:
                    row.status = EmailStatus.ARCHIVED.value
                    labels = list(row.labels or [])
                    if "INBOX" in labels:
                        labels.remove("INBOX")
                    row.labels = labels

            return True
        except Exception as e:
            logger.error("archive_email_failed", email_id=email_id, error=str(e))
            return False

    async def star_email(self, email_id: str, starred: bool = True) -> bool:
        """Star or unstar an email."""
        try:
            service = self._get_gmail_service()
            body = {"addLabelIds": ["STARRED"]} if starred else {"removeLabelIds": ["STARRED"]}

            async def _star():
                service.users().messages().modify(
                    userId="me",
                    id=email_id,
                    body=body
                ).execute()

            await self._breaker.call(_star)

            # Update DB
            async with get_session() as session:
                row = await session.get(EmailCacheModel, email_id)
                if row:
                    row.is_starred = starred

            return True
        except Exception as e:
            logger.error("star_email_failed", email_id=email_id, error=str(e))
            return False

    async def generate_digest(self) -> EmailDigest:
        """Generate email digest summary."""
        async with get_session() as session:
            # Count by category
            cat_stmt = (
                select(EmailCacheModel.category, sa_func.count())
                .group_by(EmailCacheModel.category)
            )
            cat_result = await session.execute(cat_stmt)
            by_category = {row[0]: row[1] for row in cat_result.all()}

            # Total count
            total = sum(by_category.values())

            # Unread count
            unread_stmt = (
                select(sa_func.count())
                .select_from(EmailCacheModel)
                .where(EmailCacheModel.status == EmailStatus.UNREAD.value)
            )
            unread_result = await session.execute(unread_stmt)
            unread = unread_result.scalar() or 0

            # Urgent emails (top 5)
            urgent_stmt = (
                select(EmailCacheModel)
                .where(EmailCacheModel.category == EmailCategory.URGENT.value)
                .order_by(EmailCacheModel.received_at.desc())
                .limit(5)
            )
            urgent_result = await session.execute(urgent_stmt)
            urgent_rows = urgent_result.scalars().all()

            # Important emails (top 5)
            important_stmt = (
                select(EmailCacheModel)
                .where(EmailCacheModel.category == EmailCategory.IMPORTANT.value)
                .order_by(EmailCacheModel.received_at.desc())
                .limit(5)
            )
            important_result = await session.execute(important_stmt)
            important_rows = important_result.scalars().all()

        urgent = [self._row_to_summary(r) for r in urgent_rows]
        important = [self._row_to_summary(r) for r in important_rows]

        # Generate highlights
        highlights = []
        if urgent:
            highlights.append(f"{len(urgent)} urgent email(s) need attention")
        if unread > 10:
            highlights.append(f"You have {unread} unread emails")

        return EmailDigest(
            date=datetime.utcnow(),
            total_emails=total,
            unread_emails=unread,
            by_category=by_category,
            urgent_emails=urgent,
            important_emails=important,
            highlights=highlights
        )

    # ========================================================================
    # HISTORY API - Incremental Sync (Sprint 41 Task 68)
    # ========================================================================

    async def sync_incremental(self) -> Dict[str, Any]:
        """
        Incremental sync using Gmail History API.
        Only fetches changes since last sync, much faster than full sync.
        Falls back to full sync if history ID is missing or expired.
        """
        service = self._get_gmail_service()

        # Load history_id from sync status metadata
        history_id = None
        async with get_session() as session:
            row = await session.get(SyncStatusModel, "gmail")
            if row and row.metadata_:
                history_id = row.metadata_.get("history_id")

        if not history_id:
            logger.info("no_history_id_falling_back_to_full_sync")
            return await self.sync_inbox(max_results=50, days_back=3)

        try:
            async def _list_history():
                return service.users().history().list(
                    userId="me",
                    startHistoryId=history_id,
                    historyTypes=["messageAdded", "labelAdded", "labelRemoved"],
                ).execute()

            results = await self._breaker.call(_list_history)

            new_history_id = results.get("historyId")
            histories = results.get("history", [])

            added_ids = set()
            for h in histories:
                for ma in h.get("messagesAdded", []):
                    added_ids.add(ma["message"]["id"])

            # Find which IDs already exist in DB
            existing_ids: set[str] = set()
            if added_ids:
                async with get_session() as session:
                    stmt = select(EmailCacheModel.id).where(
                        EmailCacheModel.id.in_(list(added_ids))
                    )
                    result = await session.execute(stmt)
                    existing_ids = {r[0] for r in result.all()}

            new_emails = 0
            new_email_objects: list[Email] = []

            for msg_id in added_ids:
                if msg_id in existing_ids:
                    continue
                try:
                    msg = service.users().messages().get(
                        userId="me", id=msg_id, format="full"
                    ).execute()
                    headers = self._parse_headers(msg.get("payload", {}).get("headers", []))
                    text_body, html_body = self._decode_body(msg.get("payload", {}))
                    from_addr = self._parse_email_address(headers.get("from", ""))
                    category = self._classify_email(msg, headers)

                    email = Email(
                        id=msg["id"],
                        thread_id=msg.get("threadId", msg["id"]),
                        subject=headers.get("subject", "(No Subject)"),
                        snippet=msg.get("snippet", ""),
                        body_text=text_body,
                        body_html=html_body,
                        from_address=from_addr,
                        to_addresses=[],
                        cc_addresses=[],
                        labels=msg.get("labelIds", []),
                        attachments=[],
                        category=category,
                        status=EmailStatus.UNREAD if "UNREAD" in msg.get("labelIds", []) else EmailStatus.READ,
                        is_starred="STARRED" in msg.get("labelIds", []),
                        is_important="IMPORTANT" in msg.get("labelIds", []),
                        received_at=datetime.fromtimestamp(int(msg.get("internalDate", 0)) / 1000),
                        internal_date=int(msg.get("internalDate", 0)),
                        synced_at=datetime.utcnow()
                    )
                    new_email_objects.append(email)
                    new_emails += 1

                    # Check VIP alerts
                    await self._check_alert_rules(email)

                except Exception as e:
                    logger.warning("history_message_fetch_error", id=msg_id, error=str(e))

            # Persist new emails and update history_id
            async with get_session() as session:
                for email in new_email_objects:
                    await session.merge(self._email_to_row(email))

                # Update history_id in sync status metadata
                row = await session.get(SyncStatusModel, "gmail")
                if row:
                    meta = row.metadata_ or {}
                    meta["history_id"] = str(new_history_id)
                    row.metadata_ = meta
                    row.last_sync = datetime.utcnow()
                    await session.merge(row)

            logger.info("gmail_incremental_sync_complete", new_emails=new_emails, history_changes=len(histories))
            return {"status": "success", "type": "incremental", "new_emails": new_emails}

        except Exception as e:
            if "historyId" in str(e).lower() or "404" in str(e):
                logger.info("history_expired_falling_back", error=str(e))
                return await self.sync_inbox(max_results=50, days_back=3)
            raise

    # ========================================================================
    # EMAIL ALERT SYSTEM (Sprint 41 Task 70)
    # ========================================================================

    _vip_senders: List[str] = []
    _quiet_hours: tuple = (22, 7)  # 10 PM - 7 AM

    def configure_alerts(self, vip_senders: List[str] = None, quiet_start: int = 22, quiet_end: int = 7):
        """Configure VIP senders and quiet hours."""
        if vip_senders is not None:
            self._vip_senders = [s.lower() for s in vip_senders]
        self._quiet_hours = (quiet_start, quiet_end)

        # Persist config
        config_path = self.email_path / "alert_config.json"
        config_path.write_text(json.dumps({
            "vip_senders": self._vip_senders,
            "quiet_start": quiet_start,
            "quiet_end": quiet_end,
        }))

    def _load_alert_config(self):
        """Load alert config from disk."""
        config_path = self.email_path / "alert_config.json"
        if config_path.exists():
            config = json.loads(config_path.read_text())
            self._vip_senders = config.get("vip_senders", [])
            self._quiet_hours = (config.get("quiet_start", 22), config.get("quiet_end", 7))

    def _is_quiet_hours(self) -> bool:
        """Check if current time is within quiet hours."""
        now_hour = datetime.utcnow().hour
        start, end = self._quiet_hours
        if start > end:  # Crosses midnight (e.g., 22-7)
            return now_hour >= start or now_hour < end
        return start <= now_hour < end

    async def _check_alert_rules(self, email) -> Optional[Dict]:
        """Check if an email should trigger an alert."""
        self._load_alert_config()

        from_email = email.from_address.email.lower() if hasattr(email.from_address, 'email') else ""
        from_name = email.from_address.name.lower() if hasattr(email.from_address, 'name') else ""

        alert = None

        # VIP sender alert (always fires, even in quiet hours)
        if any(vip in from_email or vip in from_name for vip in self._vip_senders):
            alert = {
                "type": "vip_sender",
                "priority": "high",
                "subject": email.subject,
                "from": from_email,
                "message": f"VIP email from {from_email}: {email.subject}",
            }

        # Urgent email alert (respects quiet hours)
        elif email.category == EmailCategory.URGENT and not self._is_quiet_hours():
            alert = {
                "type": "urgent_email",
                "priority": "high",
                "subject": email.subject,
                "from": from_email,
                "message": f"Urgent email: {email.subject}",
            }

        if alert:
            alert["timestamp"] = datetime.utcnow().isoformat()
            # Store alert
            alerts_path = self.email_path / "alerts.json"
            alerts = json.loads(alerts_path.read_text()) if alerts_path.exists() else []
            alerts.insert(0, alert)
            alerts_path.write_text(json.dumps(alerts[:100]))  # Keep last 100
            logger.info("email_alert_triggered", **alert)

        return alert

    async def get_recent_alerts(self, limit: int = 10) -> List[Dict]:
        """Get recent email alerts."""
        alerts_path = self.email_path / "alerts.json"
        if alerts_path.exists():
            alerts = json.loads(alerts_path.read_text())
            return alerts[:limit]
        return []


@lru_cache()
def get_gmail_service() -> GmailService:
    """Get singleton GmailService instance."""
    return GmailService()
