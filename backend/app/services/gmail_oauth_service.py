"""
Gmail / Calendar OAuth2 service — multi-account.

Stores credentials in `oauth_accounts` (Postgres JSONB) instead of a single
on-disk token file. Backwards compatible: callers that don't pass `account_id`
get the row marked `is_default=True`.

Schema follows fastapi-users `OAuthAccount` shape (MIT). See
CLAUDE.md "CHECK GITHUB BEFORE BUILDING".

The OAuth flow itself still uses `google-auth-oauthlib` (official Google lib).
The state file (`workspace/email/oauth_state_<state>.json`) preserves the PKCE
code_verifier across the redirect — without it, `fetch_token` fails with
`invalid_grant: Missing code verifier`.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import select

logger = structlog.get_logger()

# Lazy-loaded Google modules (heavy imports)
_google_flow = None
_google_credentials = None

# OAuth scopes for Gmail and Calendar
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]


class GmailOAuthService:
    """Multi-account Google OAuth2 service.

    Singleton facade. Every public method accepts an optional `account_id`;
    when omitted, operations target the row with `is_default=True`.
    """

    def __init__(self, workspace_path: str = "workspace"):
        self.workspace_path = Path(workspace_path)
        self.email_path = self.workspace_path / "email"
        self.email_path.mkdir(parents=True, exist_ok=True)
        self.credentials_file = self.email_path / "gmail_credentials.json"
        # Per-account refresh-failure cache so we stop retrying revoked tokens.
        self._refresh_failed: dict[str, bool] = {}
        self._ensure_client_config()

    # ------------------------------------------------------------------
    # Client-config bootstrap (unchanged)
    # ------------------------------------------------------------------

    def _ensure_client_config(self) -> None:
        if self.credentials_file.exists():
            return
        from app.infrastructure.config import get_settings
        settings = get_settings()
        if settings.google_client_id and settings.google_client_secret:
            config = {
                "web": {
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                    "redirect_uris": [settings.google_redirect_uri],
                }
            }
            self.set_client_config(config)
            logger.info("gmail_client_config_created_from_env")

    def has_client_config(self) -> bool:
        return self.credentials_file.exists()

    def set_client_config(self, config: Dict[str, Any]) -> None:
        self.credentials_file.write_text(json.dumps(config, indent=2))
        logger.info("gmail_client_config_saved")

    def _load_google_modules(self) -> None:
        global _google_flow, _google_credentials
        if _google_flow is None:
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.oauth2.credentials import Credentials
            _google_flow = InstalledAppFlow
            _google_credentials = Credentials

    # ------------------------------------------------------------------
    # Account lookup helpers
    # ------------------------------------------------------------------

    async def list_accounts(self) -> List[Dict[str, Any]]:
        from app.db.models import OAuthAccountModel
        from app.infrastructure.database import get_session
        async with get_session() as session:
            rows = (await session.execute(
                select(OAuthAccountModel).where(OAuthAccountModel.provider == "google")
                .order_by(OAuthAccountModel.connected_at)
            )).scalars().all()
            return [
                {
                    "id": r.id,
                    "label": r.label,
                    "email": r.email,
                    "is_default": r.is_default,
                    "scopes": r.scopes or [],
                    "quiet_hours": r.quiet_hours or {},
                    "connected_at": r.connected_at.isoformat() if r.connected_at else None,
                    "last_refreshed_at": r.last_refreshed_at.isoformat() if r.last_refreshed_at else None,
                    "metadata": r.metadata_ or {},
                }
                for r in rows
            ]

    async def get_account(self, account_id: Optional[str] = None) -> Optional[Any]:
        """Return the OAuthAccountModel row for `account_id`, or the default account."""
        from app.db.models import OAuthAccountModel
        from app.infrastructure.database import get_session
        async with get_session() as session:
            if account_id:
                return await session.get(OAuthAccountModel, account_id)
            row = (await session.execute(
                select(OAuthAccountModel)
                .where(OAuthAccountModel.provider == "google")
                .where(OAuthAccountModel.is_default == True)  # noqa: E712
                .limit(1)
            )).scalar_one_or_none()
            if row:
                return row
            # Fallback: the first row by connected_at
            return (await session.execute(
                select(OAuthAccountModel)
                .where(OAuthAccountModel.provider == "google")
                .order_by(OAuthAccountModel.connected_at)
                .limit(1)
            )).scalar_one_or_none()

    async def has_valid_tokens(self, account_id: Optional[str] = None) -> bool:
        creds = await self.get_credentials(account_id=account_id)
        return creds is not None and getattr(creds, "valid", False)

    # ------------------------------------------------------------------
    # OAuth flow
    # ------------------------------------------------------------------

    def get_auth_url(
        self,
        redirect_uri: Optional[str] = None,
        *,
        label: str = "personal",
    ) -> Dict[str, str]:
        """Generate an OAuth URL. `label` ("personal" / "work" / etc.) is
        recorded in the state file and applied when the callback persists the
        new credentials, so we know which account is being added."""
        if not self.has_client_config():
            raise ValueError(
                "Gmail client config not found. Download credentials.json from "
                "Google Cloud Console and call set_client_config() first."
            )
        if not redirect_uri:
            from app.infrastructure.config import get_settings
            redirect_uri = get_settings().google_redirect_uri

        self._load_google_modules()
        flow = _google_flow.from_client_secrets_file(
            str(self.credentials_file),
            scopes=GOOGLE_SCOPES,
            redirect_uri=redirect_uri,
        )
        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )

        # Persist state per `state` value so concurrent OAuth flows don't
        # clobber each other (e.g. user starts a work-add then changes their
        # mind and starts a personal re-auth).
        state_file = self.email_path / f"oauth_state_{state}.json"
        state_file.write_text(json.dumps({
            "state": state,
            "label": label,
            "redirect_uri": redirect_uri,
            "code_verifier": getattr(flow, "code_verifier", None),
            "created_at": datetime.utcnow().isoformat(),
        }))
        logger.info("gmail_auth_url_generated", state=state[:8] + "...", label=label)
        return {"auth_url": auth_url, "state": state}

    async def handle_callback(self, code: str, state: str) -> Dict[str, Any]:
        """Exchange the auth code for credentials, persist them as a row in
        `oauth_accounts`, and return the new account record."""
        if not self.has_client_config():
            raise ValueError("Gmail client config not found")

        # Find the matching state file.
        state_file = self.email_path / f"oauth_state_{state}.json"
        if not state_file.exists():
            # Backwards compat: legacy single-state file
            legacy = self.email_path / "oauth_state.json"
            if legacy.exists():
                state_file = legacy
            else:
                raise ValueError("OAuth state not found. Start auth flow again.")

        saved_state = json.loads(state_file.read_text())
        if saved_state.get("state") != state:
            raise ValueError("OAuth state mismatch. Possible CSRF attack.")

        redirect_uri = saved_state.get("redirect_uri", "http://localhost:18792/api/email/auth/callback")
        label = saved_state.get("label", "personal")

        self._load_google_modules()
        flow = _google_flow.from_client_secrets_file(
            str(self.credentials_file),
            scopes=GOOGLE_SCOPES,
            redirect_uri=redirect_uri,
        )
        verifier = saved_state.get("code_verifier")
        if verifier:
            flow.code_verifier = verifier

        flow.fetch_token(code=code)
        creds = flow.credentials
        state_file.unlink(missing_ok=True)

        # Resolve account email from Google so we can dedupe by (provider, email).
        from googleapiclient.discovery import build
        service = build("gmail", "v1", credentials=creds)
        profile = service.users().getProfile(userId="me").execute()
        email_address = profile.get("emailAddress", "unknown")

        # Upsert into oauth_accounts.
        account_id = await self._persist_account(
            email=email_address, label=label, creds=creds
        )
        self._refresh_failed.pop(account_id, None)

        # Legacy mirror so the old SyncStatusModel "connected" check still
        # reports connected. Only the default account writes here.
        try:
            from app.db.models import SyncStatusModel
            from app.infrastructure.database import get_session
            async with get_session() as session:
                row = await session.get(SyncStatusModel, "gmail")
                if not row:
                    row = SyncStatusModel(service_name="gmail", connected=True)
                    session.add(row)
                row.connected = True
                row.email_address = email_address
        except Exception as e:
            logger.debug("legacy_sync_status_mirror_skipped", error=str(e))

        logger.info("gmail_oauth_complete", email=email_address, label=label, account_id=account_id)
        return {
            "status": "connected",
            "email_address": email_address,
            "account_id": account_id,
            "label": label,
        }

    # ------------------------------------------------------------------
    # Credentials
    # ------------------------------------------------------------------

    async def get_credentials(self, account_id: Optional[str] = None) -> Optional[Any]:
        """Return refreshed credentials for the given (or default) account."""
        account = await self.get_account(account_id)
        if account is None:
            return None

        if self._refresh_failed.get(account.id):
            return None

        self._load_google_modules()
        try:
            creds = _google_credentials.from_authorized_user_info(
                account.credentials, GOOGLE_SCOPES
            )
        except Exception as e:
            logger.error("oauth_credentials_load_failed", account_id=account.id, error=str(e))
            return None

        if creds.expired and creds.refresh_token:
            try:
                from google.auth.transport.requests import Request
                creds.refresh(Request())
                await self._update_credentials(account.id, creds)
            except Exception as e:
                err = str(e)
                if "invalid_grant" in err:
                    self._refresh_failed[account.id] = True
                    logger.error(
                        "gmail_token_revoked",
                        account_id=account.id,
                        hint="Re-authenticate at /api/google/auth/start",
                    )
                else:
                    logger.error("gmail_token_refresh_failed", account_id=account.id, error=err)
                return None

        return creds if creds.valid else None

    async def _persist_account(
        self,
        *,
        email: str,
        label: str,
        creds: Any,
    ) -> str:
        from app.db.models import OAuthAccountModel
        from app.infrastructure.database import get_session
        async with get_session() as session:
            existing = (await session.execute(
                select(OAuthAccountModel)
                .where(OAuthAccountModel.provider == "google")
                .where(OAuthAccountModel.email == email)
            )).scalar_one_or_none()

            credentials_json = json.loads(creds.to_json())
            if existing:
                existing.credentials = credentials_json
                existing.label = label
                existing.scopes = list(getattr(creds, "scopes", []) or GOOGLE_SCOPES)
                existing.last_refreshed_at = datetime.now(timezone.utc)
                return existing.id

            # Promote to default if this is the only account.
            any_existing = (await session.execute(
                select(OAuthAccountModel).where(OAuthAccountModel.provider == "google").limit(1)
            )).scalar_one_or_none()
            account_id = uuid.uuid4().hex
            row = OAuthAccountModel(
                id=account_id,
                provider="google",
                label=label,
                email=email,
                credentials=credentials_json,
                scopes=list(getattr(creds, "scopes", []) or GOOGLE_SCOPES),
                quiet_hours={},
                metadata_={},
                is_default=any_existing is None,
                last_refreshed_at=datetime.now(timezone.utc),
            )
            session.add(row)
            return account_id

    async def _update_credentials(self, account_id: str, creds: Any) -> None:
        from app.db.models import OAuthAccountModel
        from app.infrastructure.database import get_session
        async with get_session() as session:
            row = await session.get(OAuthAccountModel, account_id)
            if row:
                row.credentials = json.loads(creds.to_json())
                row.last_refreshed_at = datetime.now(timezone.utc)

    async def disconnect(self, account_id: Optional[str] = None) -> bool:
        """Remove credentials for the given (or default) account from the DB
        and best-effort revoke at Google."""
        account = await self.get_account(account_id)
        if account is None:
            return False
        creds = await self.get_credentials(account.id)
        if creds:
            try:
                import requests
                requests.post(
                    "https://oauth2.googleapis.com/revoke",
                    params={"token": getattr(creds, "token", "")},
                    headers={"content-type": "application/x-www-form-urlencoded"},
                    timeout=5.0,
                )
            except Exception as e:
                logger.warning("gmail_token_revoke_failed", account_id=account.id, error=str(e))

        from app.db.models import OAuthAccountModel
        from app.infrastructure.database import get_session
        async with get_session() as session:
            row = await session.get(OAuthAccountModel, account.id)
            if row:
                await session.delete(row)
        logger.info("gmail_disconnected", account_id=account.id, email=account.email)
        return True

    async def set_default(self, account_id: str) -> None:
        """Make `account_id` the default account; demote all others."""
        from app.db.models import OAuthAccountModel
        from app.infrastructure.database import get_session
        async with get_session() as session:
            rows = (await session.execute(
                select(OAuthAccountModel).where(OAuthAccountModel.provider == "google")
            )).scalars().all()
            for r in rows:
                r.is_default = (r.id == account_id)

    async def set_quiet_hours(self, account_id: str, quiet_hours: Dict[str, Any]) -> None:
        from app.db.models import OAuthAccountModel
        from app.infrastructure.database import get_session
        async with get_session() as session:
            row = await session.get(OAuthAccountModel, account_id)
            if row:
                row.quiet_hours = quiet_hours

    async def set_label(self, account_id: str, label: str) -> None:
        from app.db.models import OAuthAccountModel
        from app.infrastructure.database import get_session
        async with get_session() as session:
            row = await session.get(OAuthAccountModel, account_id)
            if row:
                row.label = label

    async def update_account_metadata(self, account_id: str, **fields: Any) -> None:
        """Merge fields into the account's metadata JSONB (e.g. history_id, last_sync)."""
        from app.db.models import OAuthAccountModel
        from app.infrastructure.database import get_session
        async with get_session() as session:
            row = await session.get(OAuthAccountModel, account_id)
            if row:
                meta = dict(row.metadata_ or {})
                meta.update({k: v for k, v in fields.items() if v is not None})
                row.metadata_ = meta


@lru_cache()
def get_gmail_oauth_service() -> GmailOAuthService:
    return GmailOAuthService()
