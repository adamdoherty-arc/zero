"""
AIContentTools HTTP Client.

Provides communication with the AIContentTools platform (C:\\code\\AIContentTools)
running on port 8085. Follows the same pattern as LegionClient: aiohttp, circuit
breaker, retry, singleton via @lru_cache.
"""

import aiohttp
from datetime import datetime
from typing import Optional, List, Dict, Any
from functools import lru_cache
import structlog

from app.infrastructure.config import get_settings
from app.infrastructure.circuit_breaker import get_circuit_breaker

logger = structlog.get_logger(__name__)


class AIContentToolsClient:
    """HTTP client for AIContentTools API."""

    def __init__(self):
        settings = get_settings()
        self.base_url = settings.ai_content_tools_url
        self.timeout = 30
        self._session: Optional[aiohttp.ClientSession] = None
        self._breaker = get_circuit_breaker(
            "ai_content_tools", failure_threshold=5, recovery_timeout=60.0
        )

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=10, limit_per_host=5, ttl_dns_cache=300
            )
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request(
        self, method: str, endpoint: str, **kwargs
    ) -> Optional[Dict[str, Any]]:
        """Make an HTTP request with circuit breaker and retry."""
        url = f"{self.base_url}{endpoint}"

        if not self._breaker.allow_request():
            logger.warning("act_circuit_open", endpoint=endpoint)
            return None

        for attempt in range(3):
            try:
                session = await self._get_session()
                async with session.request(method, url, **kwargs) as resp:
                    if resp.status == 404:
                        return None
                    if resp.status >= 400:
                        text = await resp.text()
                        logger.warning("act_request_error", status=resp.status, body=text[:200])
                        if resp.status < 500:
                            return None
                        raise aiohttp.ClientResponseError(
                            resp.request_info, resp.history, status=resp.status
                        )
                    self._breaker.record_success()
                    return await resp.json()
            except (aiohttp.ClientError, TimeoutError) as e:
                self._breaker.record_failure()
                if attempt < 2:
                    logger.debug("act_retry", attempt=attempt + 1, error=str(e))
                    continue
                logger.error("act_request_failed", endpoint=endpoint, error=str(e))
                return None

        return None

    async def _get(self, endpoint: str, params: Optional[dict] = None) -> Optional[Dict]:
        return await self._request("GET", endpoint, params=params)

    async def _post(self, endpoint: str, json: Optional[dict] = None) -> Optional[Dict]:
        return await self._request("POST", endpoint, json=json)

    # ============================================
    # HEALTH
    # ============================================

    async def health_check(self) -> bool:
        """Check if AIContentTools is reachable."""
        try:
            result = await self._get("/api/personas")
            return result is not None
        except Exception:
            return False

    # ============================================
    # PERSONAS
    # ============================================

    async def list_personas(self) -> List[Dict[str, Any]]:
        """Get available personas from AIContentTools."""
        result = await self._get("/api/personas")
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "personas" in result:
            return result["personas"]
        return []

    # ============================================
    # CONTENT GENERATION
    # ============================================

    async def generate_content(
        self,
        workflow_type: str,
        prompt: str,
        persona_id: Optional[str] = None,
        caption: Optional[str] = None,
        hashtags: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Trigger content generation via AIContentTools.

        Args:
            workflow_type: "text_to_image", "text_to_video", "full_production"
            prompt: Generation prompt
            persona_id: Optional persona ID for style consistency
            caption: Optional caption for the content
            hashtags: Optional hashtags list
        """
        payload = {
            "workflow_type": workflow_type,
            "prompt": prompt,
        }
        if persona_id:
            payload["persona_id"] = persona_id
        if caption:
            payload["caption"] = caption
        if hashtags:
            payload["hashtags"] = hashtags

        return await self._post("/api/generate", json=payload)

    async def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Check status of a generation job."""
        return await self._get(f"/api/batch/status/{job_id}")

    # ============================================
    # BATCH QUEUE
    # ============================================

    async def queue_batch(
        self, items: List[Dict], queue_name: str = "tiktok_shop"
    ) -> Optional[Dict[str, Any]]:
        """Queue a batch of generation jobs."""
        return await self._post("/api/batch/queue", json={
            "items": items,
            "queue_name": queue_name,
        })

    # ============================================
    # PUBLISHING
    # ============================================

    async def publish_content(
        self,
        generation_ids: List[str],
        platforms: List[str],
        caption: str,
        hashtags: List[str],
        schedule_time: Optional[datetime] = None,
        persona_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Publish content to social platforms."""
        payload = {
            "generation_ids": generation_ids,
            "platforms": platforms,
            "caption": caption,
            "hashtags": hashtags,
        }
        if schedule_time:
            payload["schedule_time"] = schedule_time.isoformat()
        if persona_id:
            payload["persona_id"] = persona_id

        return await self._post("/api/publishing/publish", json=payload)

    # ============================================
    # PERFORMANCE
    # ============================================

    async def get_performance(
        self,
        generation_id: Optional[str] = None,
        platform: Optional[str] = None,
        days: int = 7,
    ) -> List[Dict[str, Any]]:
        """Get content performance metrics."""
        params = {"days": days}
        if generation_id:
            params["generation_id"] = generation_id
        if platform:
            params["platform"] = platform

        result = await self._get("/api/performance", params=params)
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "data" in result:
            return result["data"]
        return []

    async def get_performance_summary(self, days: int = 30) -> Optional[Dict[str, Any]]:
        """Get performance summary."""
        return await self._get("/api/performance/summary", params={"days": days})

    # ============================================
    # STRATEGY
    # ============================================

    async def get_strategy_recommendations(
        self,
        days_ahead: int = 7,
        personas: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get AI content strategy recommendations."""
        payload = {"days_ahead": days_ahead}
        if personas:
            payload["personas"] = personas
        return await self._post("/api/strategy/recommend", json=payload)


@lru_cache()
def get_ai_content_tools_client() -> AIContentToolsClient:
    """Get cached AIContentTools client instance."""
    return AIContentToolsClient()
