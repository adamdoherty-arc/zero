"""
Gmail OAuth2 service for authentication.
"""

import os
import json
from pathlib import Path
from typing import Optional, Dict, Any
from functools import lru_cache
from datetime import datetime
import structlog

# Google OAuth libraries (lazy import)
google_flow = None
google_credentials = None

logger = structlog.get_logger()

# OAuth scopes for Gmail and Calendar
GOOGLE_SCOPES = [
    # Gmail scopes
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/gmail.modify",
    # Calendar scopes
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]


class GmailOAuthService:
    """Service for Gmail OAuth2 authentication."""

    def __init__(self, workspace_path: str = "workspace"):
        self.workspace_path = Path(workspace_path)
        self.email_path = self.workspace_path / "email"
        self.email_path.mkdir(parents=True, exist_ok=True)
        self.credentials_file = self.email_path / "gmail_credentials.json"
        self.tokens_file = self.email_path / "gmail_tokens.json"
        self._credentials = None
        
        # Auto-create credentials from environment if not exists
        self._ensure_client_config()

    def _ensure_client_config(self):
        """Create OAuth client config from environment variables if not exists."""
        if not self.credentials_file.exists():
            from app.infrastructure.config import get_settings
            settings = get_settings()
            
            if settings.google_client_id and settings.google_client_secret:
                # Create credentials JSON from env vars
                config = {
                    "web": {
                        "client_id": settings.google_client_id,
                        "client_secret": settings.google_client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                        "redirect_uris": [settings.google_redirect_uri]
                    }
                }
                self.set_client_config(config)
                logger.info("gmail_client_config_created_from_env")

    def _load_google_modules(self):
        """Lazy load Google OAuth modules."""
        global google_flow, google_credentials
        if google_flow is None:
            try:
                from google_auth_oauthlib.flow import InstalledAppFlow
                from google.oauth2.credentials import Credentials
                google_flow = InstalledAppFlow
                google_credentials = Credentials
            except ImportError:
                raise RuntimeError(
                    "Google OAuth libraries not installed. "
                    "Install with: pip install google-auth google-auth-oauthlib google-api-python-client"
                )

    def has_client_config(self) -> bool:
        """Check if OAuth client config exists."""
        return self.credentials_file.exists()

    def set_client_config(self, config: Dict[str, Any]):
        """
        Set OAuth client configuration.

        Config should be the contents of a downloaded credentials.json
        from Google Cloud Console.
        """
        self.credentials_file.write_text(json.dumps(config, indent=2))
        logger.info("gmail_client_config_saved")

    def has_valid_tokens(self) -> bool:
        """Check if valid tokens exist."""
        if not self.tokens_file.exists():
            return False

        try:
            self._load_google_modules()
            creds = self._load_credentials()
            if creds and creds.valid:
                return True
            if creds and creds.expired and creds.refresh_token:
                # Try to refresh
                from google.auth.transport.requests import Request
                creds.refresh(Request())
                self._save_credentials(creds)
                return True
            return False
        except Exception as e:
            logger.warning("gmail_token_check_failed", error=str(e))
            return False

    def _load_credentials(self) -> Optional[Any]:
        """Load credentials from token file."""
        if not self.tokens_file.exists():
            return None

        self._load_google_modules()
        try:
            return google_credentials.from_authorized_user_file(
                str(self.tokens_file),
                GOOGLE_SCOPES
            )
        except Exception as e:
            logger.error("gmail_credentials_load_failed", error=str(e))
            return None

    def _save_credentials(self, creds):
        """Save credentials to token file."""
        self.tokens_file.write_text(creds.to_json())

    def get_auth_url(self, redirect_uri: str = None) -> Dict[str, str]:
        """
        Get OAuth authorization URL for user to visit.

        Returns dict with 'auth_url' and 'state' for CSRF protection.
        """
        if not self.has_client_config():
            raise ValueError(
                "Gmail client config not found. "
                "Download credentials.json from Google Cloud Console and "
                "call set_client_config() first."
            )

        # Use provided redirect_uri or get from config
        if not redirect_uri:
            from app.infrastructure.config import get_settings
            settings = get_settings()
            redirect_uri = settings.google_redirect_uri

        self._load_google_modules()

        flow = google_flow.from_client_secrets_file(
            str(self.credentials_file),
            scopes=GOOGLE_SCOPES,
            redirect_uri=redirect_uri
        )

        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent"  # Force consent to get refresh token
        )

        # Save state for verification
        state_file = self.email_path / "oauth_state.json"
        state_file.write_text(json.dumps({
            "state": state,
            "redirect_uri": redirect_uri,
            "created_at": datetime.utcnow().isoformat()
        }))

        logger.info("gmail_auth_url_generated", state=state[:8] + "...")
        return {
            "auth_url": auth_url,
            "state": state
        }

    def handle_callback(self, code: str, state: str) -> Dict[str, Any]:
        """
        Handle OAuth callback with authorization code.

        Returns user email and success status.
        """
        if not self.has_client_config():
            raise ValueError("Gmail client config not found")

        # Verify state
        state_file = self.email_path / "oauth_state.json"
        if not state_file.exists():
            raise ValueError("OAuth state not found. Start auth flow again.")

        saved_state = json.loads(state_file.read_text())
        if saved_state.get("state") != state:
            raise ValueError("OAuth state mismatch. Possible CSRF attack.")

        redirect_uri = saved_state.get("redirect_uri", "http://localhost:18792/api/email/auth/callback")

        self._load_google_modules()

        flow = google_flow.from_client_secrets_file(
            str(self.credentials_file),
            scopes=GOOGLE_SCOPES,
            redirect_uri=redirect_uri
        )

        # Exchange code for tokens
        flow.fetch_token(code=code)
        creds = flow.credentials

        # Save credentials
        self._save_credentials(creds)

        # Clean up state file
        state_file.unlink()

        # Get user email
        from googleapiclient.discovery import build
        service = build("gmail", "v1", credentials=creds)
        profile = service.users().getProfile(userId="me").execute()
        email_address = profile.get("emailAddress", "unknown")

        logger.info("gmail_oauth_complete", email=email_address)

        return {
            "status": "connected",
            "email_address": email_address
        }

    def get_credentials(self) -> Optional[Any]:
        """
        Get valid OAuth credentials.

        Returns credentials object for use with Gmail API.
        Refreshes if expired.
        """
        self._load_google_modules()
        creds = self._load_credentials()

        if not creds:
            return None

        if creds.expired and creds.refresh_token:
            try:
                from google.auth.transport.requests import Request
                creds.refresh(Request())
                self._save_credentials(creds)
            except Exception as e:
                logger.error("gmail_token_refresh_failed", error=str(e))
                return None

        return creds if creds.valid else None

    def disconnect(self):
        """Disconnect Gmail (revoke tokens)."""
        creds = self.get_credentials()
        if creds:
            try:
                import requests
                requests.post(
                    "https://oauth2.googleapis.com/revoke",
                    params={"token": creds.token},
                    headers={"content-type": "application/x-www-form-urlencoded"}
                )
            except Exception as e:
                logger.warning("gmail_token_revoke_failed", error=str(e))

        # Remove local tokens
        if self.tokens_file.exists():
            self.tokens_file.unlink()

        logger.info("gmail_disconnected")


@lru_cache()
def get_gmail_oauth_service() -> GmailOAuthService:
    """Get singleton GmailOAuthService instance."""
    return GmailOAuthService()
