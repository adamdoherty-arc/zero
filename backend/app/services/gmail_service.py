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
        # Per-account API client cache. Key: account_id (or "_default" for the
        # singleton account). Each entry holds a googleapiclient.discovery.Resource.
        self._services: dict[str, Any] = {}
        self._breaker = get_circuit_breaker(
            "gmail",
            failure_threshold=3,
            recovery_timeout=60.0,
        )

    async def is_connected(self) -> bool:
        """True if at least one Google account has valid tokens."""
        oauth_service = get_gmail_oauth_service()
        accounts = await oauth_service.list_accounts()
        for acct in accounts:
            if await oauth_service.has_valid_tokens(account_id=acct["id"]):
                return True
        # Fall back to the legacy SyncStatus row for installs that haven't migrated yet.
        status = await self._load_sync_status()
        return status.connected if hasattr(status, "connected") else False

    async def _get_gmail_service(self, account_id: Optional[str] = None):
        """Authenticated Gmail API client for the given (or default) account."""
        cache_key = account_id or "_default"
        cached = self._services.get(cache_key)
        if cached is not None:
            return cached

        oauth_service = get_gmail_oauth_service()
        creds = await oauth_service.get_credentials(account_id=account_id)
        if not creds:
            raise RuntimeError("Gmail not connected. Complete OAuth flow first.")
        try:
            from googleapiclient.discovery import build
            client = build("gmail", "v1", credentials=creds)
            self._services[cache_key] = client
            return client
        except ImportError:
            raise RuntimeError(
                "Google API client not installed. "
                "Install with: pip install google-api-python-client"
            )

    async def list_account_ids(self) -> list[str]:
        """All connected account ids (multi-account scheduler sync uses this)."""
        return [a["id"] for a in await get_gmail_oauth_service().list_accounts()]

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
        """Get current sync status (default account)."""
        oauth_service = get_gmail_oauth_service()
        status = await self._load_sync_status()
        status.connected = await oauth_service.has_valid_tokens()
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
            from app.infrastructure.unified_llm_client import get_unified_llm_client
            result = await get_unified_llm_client().chat(
                prompt, task_type="classification", max_tokens=20, temperature=0.1,
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
        days_back: int = 7,
        account_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Sync inbox from Gmail for one account (default if account_id is None).

        Multi-account: every cached email row is tagged with the source account_id
        so the UI can filter; history_id is stored on the account row.
        """
        service = await self._get_gmail_service(account_id=account_id)
        status = await self._load_sync_status()
        # Resolve account_id when not supplied so we can still tag rows.
        if account_id is None:
            account = await get_gmail_oauth_service().get_account()
            account_id = account.id if account else None

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

            # Upsert all emails into PostgreSQL with account tag.
            async with get_session() as session:
                for email in emails:
                    row = self._email_to_row(email)
                    row.account_id = account_id
                    await session.merge(row)

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
            # Keep only last 20 errors to prevent unbounded growth
            status.sync_errors = status.sync_errors[-20:]
            await self._save_sync_status(status)
            raise

    async def list_emails(
        self,
        category: Optional[EmailCategory] = None,
        status: Optional[EmailStatus] = None,
        limit: int = 50,
        offset: int = 0,
        account_id: Optional[str] = None,
    ) -> List[EmailSummary]:
        """List emails from DB with optional filters.

        `account_id`: filter to one account. None = all connected accounts merged.
        """
        async with get_session() as session:
            stmt = select(EmailCacheModel)

            if category:
                stmt = stmt.where(EmailCacheModel.category == category.value)
            if status:
                stmt = stmt.where(EmailCacheModel.status == status.value)
            if account_id:
                stmt = stmt.where(EmailCacheModel.account_id == account_id)

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
        service = await self._get_gmail_service()

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
            service = await self._get_gmail_service()

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
            service = await self._get_gmail_service()

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

    async def trash_email(self, email_id: str) -> bool:
        """Move email to Trash (recoverable for 30 days). Uses Gmail TRASH label.

        Distinct from archive_email which only removes INBOX. trash_email also
        removes INBOX and adds TRASH so the message disappears from the inbox
        view and lands in the user's Trash folder.
        """
        try:
            service = await self._get_gmail_service()

            async def _trash():
                service.users().messages().modify(
                    userId="me",
                    id=email_id,
                    body={"addLabelIds": ["TRASH"], "removeLabelIds": ["INBOX", "UNREAD"]},
                ).execute()

            await self._breaker.call(_trash)

            async with get_session() as session:
                row = await session.get(EmailCacheModel, email_id)
                if row:
                    row.status = EmailStatus.DELETED.value
                    labels = list(row.labels or [])
                    if "INBOX" in labels:
                        labels.remove("INBOX")
                    if "UNREAD" in labels:
                        labels.remove("UNREAD")
                    if "TRASH" not in labels:
                        labels.append("TRASH")
                    row.labels = labels

            return True
        except Exception as e:
            logger.error("trash_email_failed", email_id=email_id, error=str(e))
            return False

    async def send_email(
        self,
        *,
        to: str,
        subject: str,
        body_text: str,
        in_reply_to: Optional[str] = None,
        references: Optional[str] = None,
        thread_id: Optional[str] = None,
    ) -> Optional[str]:
        """Send an email via the Gmail API. Returns the new message id on success.

        When `in_reply_to` is provided the message is a reply: the In-Reply-To
        and References headers are set, the subject is prefixed with 'Re:' if
        not already, and `thread_id` (Gmail's thread id, not RFC message id)
        keeps the message in the same thread.
        """
        try:
            from email.message import EmailMessage

            service = await self._get_gmail_service()
            msg = EmailMessage()
            msg["To"] = to
            subj = subject
            if in_reply_to and not subj.lower().startswith("re:"):
                subj = f"Re: {subj}"
            msg["Subject"] = subj
            if in_reply_to:
                msg["In-Reply-To"] = in_reply_to
                msg["References"] = references or in_reply_to
            msg.set_content(body_text)

            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            payload: Dict[str, Any] = {"raw": raw}
            if thread_id:
                payload["threadId"] = thread_id

            async def _send():
                return service.users().messages().send(userId="me", body=payload).execute()

            sent = await self._breaker.call(_send)
            sent_id = sent.get("id") if isinstance(sent, dict) else None
            logger.info(
                "email_sent",
                to=to,
                subject=subj,
                in_reply_to=in_reply_to,
                sent_id=sent_id,
            )
            return sent_id
        except Exception as e:
            logger.error("send_email_failed", to=to, subject=subject, error=str(e))
            return None

    async def star_email(self, email_id: str, starred: bool = True) -> bool:
        """Star or unstar an email."""
        try:
            service = await self._get_gmail_service()
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

    async def sync_incremental(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Incremental sync via Gmail History API for one account.

        Multi-account: history_id lives on the account's `oauth_accounts.metadata`.
        Falls back to full `sync_inbox(account_id=...)` when no history_id is
        cached or the cached id has expired (Gmail returns 404 after ~7 days).
        """
        service = await self._get_gmail_service(account_id=account_id)

        oauth_svc = get_gmail_oauth_service()
        account = await oauth_svc.get_account(account_id)
        account_id = account.id if account else account_id  # resolve default

        # Load history_id from the account's metadata; fall back to legacy
        # SyncStatusModel for installs that pre-date the multi-account migration.
        history_id = None
        if account:
            history_id = (account.metadata_ or {}).get("history_id")
        if not history_id:
            async with get_session() as session:
                row = await session.get(SyncStatusModel, "gmail")
                if row and row.metadata_:
                    history_id = row.metadata_.get("history_id")

        if not history_id:
            logger.info("no_history_id_falling_back_to_full_sync", account_id=account_id)
            return await self.sync_inbox(max_results=50, days_back=3, account_id=account_id)

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

            # Persist new emails (tagged with account_id) and update history_id.
            async with get_session() as session:
                for email in new_email_objects:
                    row = self._email_to_row(email)
                    row.account_id = account_id
                    await session.merge(row)

            # Update history_id on the account row (preferred) and mirror to
            # the legacy SyncStatus row for the default account so old code
            # that reads from SyncStatusModel keeps working.
            if new_history_id:
                if account_id:
                    await oauth_svc.update_account_metadata(
                        account_id, history_id=str(new_history_id)
                    )
                async with get_session() as session:
                    legacy = await session.get(SyncStatusModel, "gmail")
                    if legacy:
                        meta = legacy.metadata_ or {}
                        meta["history_id"] = str(new_history_id)
                        legacy.metadata_ = meta
                        legacy.last_sync = datetime.utcnow()
                        await session.merge(legacy)

            logger.info(
                "gmail_incremental_sync_complete",
                account_id=account_id,
                new_emails=new_emails,
                history_changes=len(histories),
            )
            return {"status": "success", "type": "incremental", "new_emails": new_emails, "account_id": account_id}

        except Exception as e:
            if "historyId" in str(e).lower() or "404" in str(e):
                logger.info("history_expired_falling_back", account_id=account_id, error=str(e))
                return await self.sync_inbox(max_results=50, days_back=3, account_id=account_id)
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
