"""
TikTok Content Posting API v2 Client.

Handles OAuth2 authorization, video upload, and content posting to TikTok.
Uses the same patterns as ai_content_tools_client.py: aiohttp, circuit breaker,
retry, singleton via @lru_cache.

TikTok API Docs: https://developers.tiktok.com/doc/content-posting-api-get-started
"""

import aiohttp
import urllib.parse
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from functools import lru_cache
import structlog

from app.infrastructure.config import get_settings
from app.infrastructure.circuit_breaker import get_circuit_breaker

logger = structlog.get_logger(__name__)

TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_API_BASE = "https://open.tiktokapis.com"


class TikTokApiClient:
    """Client for TikTok Content Posting API v2."""

    def __init__(self):
        settings = get_settings()
        self.client_key = settings.tiktok_client_key
        self.client_secret = settings.tiktok_client_secret
        self.redirect_uri = settings.tiktok_redirect_uri
        self.timeout = 30
        self._session: Optional[aiohttp.ClientSession] = None
        self._breaker = get_circuit_breaker(
            "tiktok_api", failure_threshold=5, recovery_timeout=120.0
        )
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
        self._open_id: Optional[str] = None

    @property
    def is_configured(self) -> bool:
        return bool(self.client_key and self.client_secret)

    @property
    def is_authorized(self) -> bool:
        return bool(self._access_token and self._open_id)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(limit=5, limit_per_host=3, ttl_dns_cache=300)
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ============================================
    # TOKEN MANAGEMENT
    # ============================================

    async def load_tokens_from_db(self):
        """Load stored OAuth tokens from ServiceConfig table."""
        try:
            from app.infrastructure.database import get_session
            from sqlalchemy import select
            from app.db.models import ServiceConfigModel

            async with get_session() as session:
                result = await session.execute(
                    select(ServiceConfigModel).where(
                        ServiceConfigModel.service_name == "tiktok_oauth"
                    )
                )
                row = result.scalar_one_or_none()
                if row and row.config:
                    config = row.config
                    self._access_token = config.get("access_token")
                    self._refresh_token = config.get("refresh_token")
                    self._open_id = config.get("open_id")
                    expires_at = config.get("expires_at")
                    if expires_at:
                        self._token_expires_at = datetime.fromisoformat(expires_at)
                    logger.info("tiktok_tokens_loaded", open_id=self._open_id)
        except Exception as e:
            logger.warning("tiktok_tokens_load_failed", error=str(e))

    async def _save_tokens_to_db(self):
        """Persist OAuth tokens to ServiceConfig table."""
        try:
            from app.infrastructure.database import get_session
            from sqlalchemy import select
            from app.db.models import ServiceConfigModel

            config = {
                "access_token": self._access_token,
                "refresh_token": self._refresh_token,
                "open_id": self._open_id,
                "expires_at": self._token_expires_at.isoformat() if self._token_expires_at else None,
            }

            async with get_session() as session:
                result = await session.execute(
                    select(ServiceConfigModel).where(
                        ServiceConfigModel.service_name == "tiktok_oauth"
                    )
                )
                row = result.scalar_one_or_none()
                if row:
                    row.config = config
                else:
                    session.add(ServiceConfigModel(
                        service_name="tiktok_oauth",
                        config=config,
                    ))
                await session.flush()
                logger.info("tiktok_tokens_saved")
        except Exception as e:
            logger.error("tiktok_tokens_save_failed", error=str(e))

    # ============================================
    # OAUTH2 FLOW
    # ============================================

    def get_authorize_url(self, state: str = "zero_tiktok") -> Optional[str]:
        """Generate TikTok OAuth authorization URL."""
        if not self.is_configured:
            return None

        params = {
            "client_key": self.client_key,
            "response_type": "code",
            "scope": "user.info.basic,video.publish,video.upload",
            "redirect_uri": self.redirect_uri,
            "state": state,
        }
        return f"{TIKTOK_AUTH_URL}?{urllib.parse.urlencode(params)}"

    async def exchange_code(self, code: str) -> bool:
        """Exchange authorization code for access token."""
        if not self.is_configured:
            return False

        try:
            session = await self._get_session()
            payload = {
                "client_key": self.client_key,
                "client_secret": self.client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": self.redirect_uri,
            }

            async with session.post(TIKTOK_TOKEN_URL, json=payload) as resp:
                data = await resp.json()
                if resp.status != 200 or data.get("error"):
                    logger.error("tiktok_token_exchange_failed", data=data)
                    return False

                self._access_token = data.get("access_token")
                self._refresh_token = data.get("refresh_token")
                self._open_id = data.get("open_id")
                expires_in = data.get("expires_in", 86400)
                self._token_expires_at = datetime.now(timezone.utc).replace(
                    microsecond=0
                )
                from datetime import timedelta
                self._token_expires_at += timedelta(seconds=expires_in)

                await self._save_tokens_to_db()
                logger.info("tiktok_authorized", open_id=self._open_id)
                return True

        except Exception as e:
            logger.error("tiktok_code_exchange_error", error=str(e))
            return False

    async def refresh_access_token(self) -> bool:
        """Refresh expired access token."""
        if not self._refresh_token or not self.is_configured:
            return False

        try:
            session = await self._get_session()
            payload = {
                "client_key": self.client_key,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
            }

            async with session.post(TIKTOK_TOKEN_URL, json=payload) as resp:
                data = await resp.json()
                if resp.status != 200 or data.get("error"):
                    logger.error("tiktok_token_refresh_failed", data=data)
                    return False

                self._access_token = data.get("access_token")
                self._refresh_token = data.get("refresh_token", self._refresh_token)
                expires_in = data.get("expires_in", 86400)
                from datetime import timedelta
                self._token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

                await self._save_tokens_to_db()
                logger.info("tiktok_token_refreshed")
                return True

        except Exception as e:
            logger.error("tiktok_refresh_error", error=str(e))
            return False

    async def _ensure_valid_token(self) -> bool:
        """Ensure we have a valid, non-expired access token."""
        if not self._access_token:
            await self.load_tokens_from_db()

        if not self._access_token:
            return False

        if self._token_expires_at and datetime.now(timezone.utc) >= self._token_expires_at:
            return await self.refresh_access_token()

        return True

    # ============================================
    # API REQUESTS
    # ============================================

    async def _api_request(
        self, method: str, endpoint: str, **kwargs
    ) -> Optional[Dict[str, Any]]:
        """Make an authenticated API request with circuit breaker."""
        if not await self._ensure_valid_token():
            logger.warning("tiktok_not_authorized")
            return None

        if not self._breaker.allow_request():
            logger.warning("tiktok_circuit_open", endpoint=endpoint)
            return None

        url = f"{TIKTOK_API_BASE}{endpoint}"
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._access_token}"

        for attempt in range(3):
            try:
                session = await self._get_session()
                async with session.request(method, url, headers=headers, **kwargs) as resp:
                    if resp.status == 401:
                        if await self.refresh_access_token():
                            headers["Authorization"] = f"Bearer {self._access_token}"
                            continue
                        return None

                    if resp.status >= 400:
                        text = await resp.text()
                        logger.warning("tiktok_api_error", status=resp.status, body=text[:300])
                        if resp.status < 500:
                            self._breaker.record_success()
                            return {"error": text, "status": resp.status}
                        raise aiohttp.ClientResponseError(
                            resp.request_info, resp.history, status=resp.status
                        )

                    self._breaker.record_success()
                    return await resp.json()

            except (aiohttp.ClientError, TimeoutError) as e:
                self._breaker.record_failure()
                if attempt < 2:
                    logger.debug("tiktok_retry", attempt=attempt + 1, error=str(e))
                    continue
                logger.error("tiktok_request_failed", endpoint=endpoint, error=str(e))
                return None

        return None

    # ============================================
    # CONTENT POSTING API v2
    # ============================================

    async def init_video_upload(
        self,
        video_size: int,
        chunk_size: int = 10_000_000,
        total_chunk_count: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """Initialize video upload to get upload URL.

        Returns: {"publish_id": "...", "upload_url": "..."}
        """
        payload = {
            "post_info": {
                "title": "",
                "privacy_level": "SELF_ONLY",  # Start as private, update after review
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": video_size,
                "chunk_size": chunk_size,
                "total_chunk_count": total_chunk_count,
            },
        }
        return await self._api_request(
            "POST",
            "/v2/post/publish/content/init/",
            json=payload,
        )

    async def upload_video_chunk(
        self, upload_url: str, chunk_data: bytes, content_range: str
    ) -> bool:
        """Upload a video chunk to TikTok's upload URL."""
        try:
            session = await self._get_session()
            headers = {
                "Content-Type": "video/mp4",
                "Content-Range": content_range,
            }
            async with session.put(upload_url, data=chunk_data, headers=headers) as resp:
                return resp.status in (200, 201, 206)
        except Exception as e:
            logger.error("tiktok_upload_chunk_failed", error=str(e))
            return False

    async def create_post(
        self,
        caption: str,
        video_url: Optional[str] = None,
        privacy_level: str = "SELF_ONLY",
        disable_comment: bool = False,
        disable_duet: bool = False,
        disable_stitch: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Create a TikTok post with a video URL (pull from URL method).

        This uses the 'PULL_FROM_URL' source which is simpler for hosted videos.
        """
        payload = {
            "post_info": {
                "title": caption[:150],  # TikTok caption limit
                "privacy_level": privacy_level,
                "disable_comment": disable_comment,
                "disable_duet": disable_duet,
                "disable_stitch": disable_stitch,
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "video_url": video_url,
            },
        }
        return await self._api_request(
            "POST",
            "/v2/post/publish/content/init/",
            json=payload,
        )

    async def get_post_status(self, publish_id: str) -> Optional[Dict[str, Any]]:
        """Check the publishing status of a post."""
        return await self._api_request(
            "POST",
            "/v2/post/publish/status/fetch/",
            json={"publish_id": publish_id},
        )

    # ============================================
    # STATUS
    # ============================================

    def get_status(self) -> Dict[str, Any]:
        """Get current TikTok API status for the frontend."""
        return {
            "configured": self.is_configured,
            "authorized": self.is_authorized,
            "open_id": self._open_id,
            "token_expires_at": self._token_expires_at.isoformat() if self._token_expires_at else None,
            "setup_instructions": self._get_setup_instructions() if not self.is_configured else None,
        }

    def _get_setup_instructions(self) -> List[Dict[str, str]]:
        return [
            {
                "step": "1",
                "title": "Register as TikTok Developer",
                "description": "Go to developers.tiktok.com and create a developer account.",
                "link": "https://developers.tiktok.com",
            },
            {
                "step": "2",
                "title": "Create an App",
                "description": "Create a new app and enable 'Content Posting API' and 'Login Kit' products.",
            },
            {
                "step": "3",
                "title": "Configure Redirect URI",
                "description": f"Set the redirect URI to: {self.redirect_uri}",
            },
            {
                "step": "4",
                "title": "Add Environment Variables",
                "description": "Add ZERO_TIKTOK_CLIENT_KEY and ZERO_TIKTOK_CLIENT_SECRET to your .env file or docker-compose.sprint.yml.",
            },
            {
                "step": "5",
                "title": "Rebuild & Connect",
                "description": "Rebuild zero-api, then click 'Connect TikTok' in the UI to authorize.",
            },
        ]


@lru_cache()
def get_tiktok_api_client() -> TikTokApiClient:
    """Get cached TikTok API client instance."""
    return TikTokApiClient()
