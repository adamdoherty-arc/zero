"""
Gmail service for email operations.
"""

import json
import base64
from pathlib import Path
from typing import Optional, List, Dict, Any
from functools import lru_cache
from datetime import datetime, timedelta
import structlog

from app.models.email import (
    Email, EmailSummary, EmailThread, EmailLabel,
    EmailCategory, EmailStatus, EmailAddress, EmailAttachment,
    EmailSyncStatus, EmailDigest
)
from app.services.gmail_oauth_service import get_gmail_oauth_service

logger = structlog.get_logger()


class GmailService:
    """Service for Gmail operations."""

    def __init__(self, workspace_path: str = "workspace"):
        self.workspace_path = Path(workspace_path)
        self.email_path = self.workspace_path / "email"
        self.email_path.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.email_path / "email_cache.json"
        self.sync_file = self.email_path / "sync_status.json"
        self._service = None
        self._ensure_storage()

    def _ensure_storage(self):
        """Ensure storage files exist."""
        if not self.cache_file.exists():
            self.cache_file.write_text(json.dumps({"emails": [], "last_sync": None}))
        if not self.sync_file.exists():
            self.sync_file.write_text(json.dumps({
                "connected": False,
                "email_address": None,
                "last_sync": None,
                "total_messages": 0,
                "unread_count": 0,
                "sync_errors": []
            }))

    def is_connected(self) -> bool:
        """Check if Gmail is configured and connected."""
        status = self._load_sync_status()
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

    def _load_cache(self) -> Dict[str, Any]:
        """Load email cache."""
        try:
            return json.loads(self.cache_file.read_text())
        except Exception:
            return {"emails": [], "last_sync": None}

    def _save_cache(self, cache: Dict[str, Any]):
        """Save email cache."""
        self.cache_file.write_text(json.dumps(cache, indent=2, default=str))

    def _load_sync_status(self) -> EmailSyncStatus:
        """Load sync status."""
        try:
            data = json.loads(self.sync_file.read_text())
            return EmailSyncStatus(**data)
        except Exception:
            return EmailSyncStatus()

    def _save_sync_status(self, status: EmailSyncStatus):
        """Save sync status."""
        self.sync_file.write_text(json.dumps(status.model_dump(), indent=2, default=str))

    def get_sync_status(self) -> EmailSyncStatus:
        """Get current sync status."""
        oauth_service = get_gmail_oauth_service()
        status = self._load_sync_status()
        status.connected = oauth_service.has_valid_tokens()
        return status

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
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "http://localhost:11434/api/generate",
                    json={"model": "qwen3:32b", "prompt": prompt, "stream": False,
                          "options": {"num_predict": 20, "temperature": 0.1}},
                )
                if resp.status_code == 200:
                    result = resp.json().get("response", "").strip().upper()
                    # Extract category from response
                    for cat in EmailCategory:
                        if cat.value.upper() in result:
                            return cat
        except Exception as e:
            logger.debug("ai_classification_fallback", error=str(e))

        return EmailCategory.NORMAL

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
        status = self._load_sync_status()

        # Build query for recent emails
        after_date = datetime.utcnow() - timedelta(days=days_back)
        query = f"after:{after_date.strftime('%Y/%m/%d')}"

        try:
            # Get message list
            results = service.users().messages().list(
                userId="me",
                q=query,
                maxResults=max_results
            ).execute()

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
                    emails.append(email.model_dump())

                except Exception as e:
                    errors.append(f"Error fetching {msg_ref['id']}: {str(e)}")
                    logger.warning("gmail_message_fetch_error", id=msg_ref["id"], error=str(e))

            # Update cache
            cache = {"emails": emails, "last_sync": datetime.utcnow().isoformat()}
            self._save_cache(cache)

            # Get profile for email address
            profile = service.users().getProfile(userId="me").execute()

            # Update sync status
            unread = len([e for e in emails if e.get("status") == EmailStatus.UNREAD.value])
            status = EmailSyncStatus(
                connected=True,
                email_address=profile.get("emailAddress"),
                last_sync=datetime.utcnow(),
                total_messages=len(emails),
                unread_count=unread,
                sync_errors=errors
            )
            self._save_sync_status(status)

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
            self._save_sync_status(status)
            raise

    async def list_emails(
        self,
        category: Optional[EmailCategory] = None,
        status: Optional[EmailStatus] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[EmailSummary]:
        """List emails from cache with optional filters."""
        cache = self._load_cache()
        emails = cache.get("emails", [])

        # Apply filters
        if category:
            emails = [e for e in emails if e.get("category") == category.value]
        if status:
            emails = [e for e in emails if e.get("status") == status.value]

        # Sort by received date (newest first)
        emails.sort(key=lambda x: x.get("internal_date", 0), reverse=True)

        # Paginate
        emails = emails[offset:offset + limit]

        # Convert to summaries
        return [
            EmailSummary(
                id=e["id"],
                thread_id=e["thread_id"],
                subject=e["subject"],
                snippet=e["snippet"],
                from_address=EmailAddress(**e["from_address"]),
                category=EmailCategory(e.get("category", "normal")),
                status=EmailStatus(e.get("status", "unread")),
                is_starred=e.get("is_starred", False),
                is_important=e.get("is_important", False),
                has_attachments=len(e.get("attachments", [])) > 0,
                received_at=datetime.fromisoformat(e["received_at"]) if isinstance(e["received_at"], str) else e["received_at"]
            )
            for e in emails
        ]

    async def get_email(self, email_id: str) -> Optional[Email]:
        """Get full email by ID."""
        cache = self._load_cache()
        for e in cache.get("emails", []):
            if e["id"] == email_id:
                return Email(**e)
        return None

    async def get_labels(self) -> List[EmailLabel]:
        """Get Gmail labels."""
        service = self._get_gmail_service()

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

    async def mark_as_read(self, email_id: str) -> bool:
        """Mark email as read."""
        try:
            service = self._get_gmail_service()
            service.users().messages().modify(
                userId="me",
                id=email_id,
                body={"removeLabelIds": ["UNREAD"]}
            ).execute()

            # Update cache
            cache = self._load_cache()
            for e in cache.get("emails", []):
                if e["id"] == email_id:
                    e["status"] = EmailStatus.READ.value
                    e["labels"] = [l for l in e.get("labels", []) if l != "UNREAD"]
            self._save_cache(cache)

            return True
        except Exception as e:
            logger.error("mark_as_read_failed", email_id=email_id, error=str(e))
            return False

    async def archive_email(self, email_id: str) -> bool:
        """Archive email (remove from inbox)."""
        try:
            service = self._get_gmail_service()
            service.users().messages().modify(
                userId="me",
                id=email_id,
                body={"removeLabelIds": ["INBOX"]}
            ).execute()

            # Update cache
            cache = self._load_cache()
            for e in cache.get("emails", []):
                if e["id"] == email_id:
                    e["status"] = EmailStatus.ARCHIVED.value
                    e["labels"] = [l for l in e.get("labels", []) if l != "INBOX"]
            self._save_cache(cache)

            return True
        except Exception as e:
            logger.error("archive_email_failed", email_id=email_id, error=str(e))
            return False

    async def star_email(self, email_id: str, starred: bool = True) -> bool:
        """Star or unstar an email."""
        try:
            service = self._get_gmail_service()
            body = {"addLabelIds": ["STARRED"]} if starred else {"removeLabelIds": ["STARRED"]}
            service.users().messages().modify(
                userId="me",
                id=email_id,
                body=body
            ).execute()

            # Update cache
            cache = self._load_cache()
            for e in cache.get("emails", []):
                if e["id"] == email_id:
                    e["is_starred"] = starred
            self._save_cache(cache)

            return True
        except Exception as e:
            logger.error("star_email_failed", email_id=email_id, error=str(e))
            return False

    async def generate_digest(self) -> EmailDigest:
        """Generate email digest summary."""
        cache = self._load_cache()
        emails = cache.get("emails", [])

        # Count by category
        by_category = {}
        for e in emails:
            cat = e.get("category", "normal")
            by_category[cat] = by_category.get(cat, 0) + 1

        # Get urgent and important emails
        urgent = [
            EmailSummary(
                id=e["id"],
                thread_id=e["thread_id"],
                subject=e["subject"],
                snippet=e["snippet"],
                from_address=EmailAddress(**e["from_address"]),
                category=EmailCategory(e.get("category", "normal")),
                status=EmailStatus(e.get("status", "unread")),
                is_starred=e.get("is_starred", False),
                is_important=e.get("is_important", False),
                has_attachments=len(e.get("attachments", [])) > 0,
                received_at=datetime.fromisoformat(e["received_at"]) if isinstance(e["received_at"], str) else e["received_at"]
            )
            for e in emails
            if e.get("category") == EmailCategory.URGENT.value
        ][:5]

        important = [
            EmailSummary(
                id=e["id"],
                thread_id=e["thread_id"],
                subject=e["subject"],
                snippet=e["snippet"],
                from_address=EmailAddress(**e["from_address"]),
                category=EmailCategory(e.get("category", "normal")),
                status=EmailStatus(e.get("status", "unread")),
                is_starred=e.get("is_starred", False),
                is_important=e.get("is_important", False),
                has_attachments=len(e.get("attachments", [])) > 0,
                received_at=datetime.fromisoformat(e["received_at"]) if isinstance(e["received_at"], str) else e["received_at"]
            )
            for e in emails
            if e.get("category") == EmailCategory.IMPORTANT.value
        ][:5]

        unread = len([e for e in emails if e.get("status") == EmailStatus.UNREAD.value])

        # Generate highlights
        highlights = []
        if urgent:
            highlights.append(f"{len(urgent)} urgent email(s) need attention")
        if unread > 10:
            highlights.append(f"You have {unread} unread emails")

        return EmailDigest(
            date=datetime.utcnow(),
            total_emails=len(emails),
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
        sync_status = self._load_sync_status()
        cache = self._load_cache()
        history_id = cache.get("history_id")

        if not history_id:
            logger.info("no_history_id_falling_back_to_full_sync")
            return await self.sync_inbox(max_results=50, days_back=3)

        try:
            results = service.users().history().list(
                userId="me",
                startHistoryId=history_id,
                historyTypes=["messageAdded", "labelAdded", "labelRemoved"],
            ).execute()

            new_history_id = results.get("historyId")
            histories = results.get("history", [])

            added_ids = set()
            for h in histories:
                for ma in h.get("messagesAdded", []):
                    added_ids.add(ma["message"]["id"])

            new_emails = 0
            existing_emails = cache.get("emails", [])
            existing_ids = {e["id"] for e in existing_emails}

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
                    existing_emails.insert(0, email.model_dump())
                    new_emails += 1

                    # Check VIP alerts
                    await self._check_alert_rules(email)

                except Exception as e:
                    logger.warning("history_message_fetch_error", id=msg_id, error=str(e))

            cache["emails"] = existing_emails
            cache["history_id"] = new_history_id
            cache["last_sync"] = datetime.utcnow().isoformat()
            self._save_cache(cache)

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
