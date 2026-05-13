"""
Browser / computer-use control service.

openhuman ships browser + computer control in its default agent toolbelt.
Zero gets a minimal, vendor-neutral wrapper here so any agent / skill can
say "open this URL, click X, fill Y, read screen". Two backends supported:

  1. **Playwright** (preferred) — full programmatic browser control. Used
     when the optional ``playwright`` dependency is installed.
  2. **Stub** — when Playwright is missing, every call returns a structured
     "unavailable" response so callers know to fall back to text-only paths.

This module deliberately stays small. Anything more elaborate (screenshot
diffing, computer-use OCR loops, visual reasoning) belongs in a dedicated
agent on top of this primitive.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


# Safety: never let a browser-use call dwell on a domain longer than this.
DEFAULT_TIMEOUT_S = 30.0
MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024  # 5 MB cap


@dataclass
class BrowserSession:
    id: str
    url: str
    started_at: str
    last_action_at: Optional[str] = None
    action_count: int = 0
    closed: bool = False
    errors: list[str] = field(default_factory=list)


@dataclass
class BrowserCommand:
    """A single discrete action the agent wants the browser to perform."""
    kind: str  # "open" | "click" | "type" | "wait" | "screenshot" | "extract_text" | "scroll"
    target: Optional[str] = None  # CSS selector or text label
    value: Optional[str] = None   # text to type, URL to open, etc.
    timeout_s: float = DEFAULT_TIMEOUT_S


@dataclass
class BrowserResult:
    ok: bool
    kind: str
    text: Optional[str] = None
    url: Optional[str] = None
    screenshot_b64: Optional[str] = None
    error: Optional[str] = None
    duration_ms: int = 0


class BrowserControlService:
    """Headless-browser primitive. Playwright when installed, stub otherwise."""

    def __init__(self) -> None:
        self._playwright = self._init_playwright()
        self._sessions: dict[str, BrowserSession] = {}
        self._page_handles: dict[str, Any] = {}
        # Allow-list of URL prefixes that the agent is permitted to navigate
        # to. Empty list = no restriction. Set via env at deploy time:
        #   BROWSER_CONTROL_ALLOWLIST="https://example.com,https://other.com"
        import os
        raw = os.getenv("BROWSER_CONTROL_ALLOWLIST", "").strip()
        self._allowlist: tuple[str, ...] = tuple(
            s.strip() for s in raw.split(",") if s.strip()
        )

    def _init_playwright(self):
        try:
            from playwright.async_api import async_playwright  # type: ignore[import-not-found]
            logger.info("browser_control_playwright_available")
            return async_playwright
        except ImportError:
            logger.debug("browser_control_playwright_not_installed")
            return None

    def is_available(self) -> bool:
        return self._playwright is not None

    def _url_allowed(self, url: str) -> bool:
        if not self._allowlist:
            return True
        return any(url.startswith(prefix) for prefix in self._allowlist)

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def open(self, url: str, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> BrowserResult:
        """Open a URL in a fresh headless tab. Returns a result with the
        landing URL + a screenshot if the backend is available."""
        if not self._url_allowed(url):
            return BrowserResult(
                ok=False, kind="open", error=f"URL '{url}' not in allowlist"
            )
        if not self.is_available():
            return BrowserResult(
                ok=False, kind="open", error="playwright not installed"
            )

        from datetime import datetime
        import uuid

        session_id = uuid.uuid4().hex[:12]
        try:
            pw = await self._playwright().__aenter__()  # type: ignore[misc]
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            response = await page.goto(url, timeout=timeout_s * 1000)
            self._page_handles[session_id] = {
                "pw": pw,
                "browser": browser,
                "context": context,
                "page": page,
            }
            self._sessions[session_id] = BrowserSession(
                id=session_id,
                url=url,
                started_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
            )
            return BrowserResult(
                ok=True,
                kind="open",
                url=str(response.url if response else url),
                text=f"session={session_id}",
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("browser_control_open_failed", error=str(e))
            return BrowserResult(ok=False, kind="open", error=str(e))

    async def close(self, session_id: str) -> BrowserResult:
        handles = self._page_handles.pop(session_id, None)
        session = self._sessions.get(session_id)
        if session:
            session.closed = True
        if handles:
            try:
                await handles["browser"].close()
            except Exception:
                pass
            try:
                await handles["pw"].__aexit__(None, None, None)
            except Exception:
                pass
        return BrowserResult(ok=True, kind="close", text=session_id)

    # ------------------------------------------------------------------
    # Actions on an open session
    # ------------------------------------------------------------------

    async def click(self, session_id: str, target: str) -> BrowserResult:
        return await self._with_page(session_id, "click", self._do_click, target)

    async def type_text(self, session_id: str, target: str, value: str) -> BrowserResult:
        return await self._with_page(
            session_id, "type", self._do_type, target, value
        )

    async def extract_text(self, session_id: str, target: Optional[str] = None) -> BrowserResult:
        return await self._with_page(
            session_id, "extract_text", self._do_extract_text, target
        )

    async def screenshot(self, session_id: str) -> BrowserResult:
        return await self._with_page(session_id, "screenshot", self._do_screenshot)

    async def _with_page(self, session_id: str, kind: str, fn, *args):
        if not self.is_available():
            return BrowserResult(ok=False, kind=kind, error="playwright not installed")
        handles = self._page_handles.get(session_id)
        session = self._sessions.get(session_id)
        if not handles or not session or session.closed:
            return BrowserResult(ok=False, kind=kind, error=f"no open session {session_id}")
        try:
            result = await fn(handles["page"], *args)
            session.action_count += 1
            from datetime import datetime
            session.last_action_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
            return result
        except Exception as e:  # noqa: BLE001
            session.errors.append(str(e))
            return BrowserResult(ok=False, kind=kind, error=str(e))

    async def _do_click(self, page, target: str) -> BrowserResult:
        await page.click(target, timeout=10000)
        return BrowserResult(ok=True, kind="click", text=target)

    async def _do_type(self, page, target: str, value: str) -> BrowserResult:
        await page.fill(target, value, timeout=10000)
        return BrowserResult(ok=True, kind="type", text=f"{target}={len(value)} chars")

    async def _do_extract_text(self, page, target: Optional[str]) -> BrowserResult:
        if target:
            text = await page.inner_text(target, timeout=10000)
        else:
            text = await page.inner_text("body")
        # Compact tool output through TokenJuice so the LLM doesn't drown
        # in nav chrome.
        try:
            from app.services.tool_output_helpers import compact_file_read
            text = compact_file_read(text, label="browser_extract")
        except Exception:
            pass
        return BrowserResult(ok=True, kind="extract_text", text=text)

    async def _do_screenshot(self, page) -> BrowserResult:
        import base64
        raw = await page.screenshot()
        if len(raw) > MAX_SCREENSHOT_BYTES:
            return BrowserResult(
                ok=False,
                kind="screenshot",
                error=f"screenshot exceeded {MAX_SCREENSHOT_BYTES} bytes",
            )
        return BrowserResult(
            ok=True,
            kind="screenshot",
            screenshot_b64=base64.b64encode(raw).decode("ascii"),
        )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_sessions(self) -> list[dict]:
        out = []
        for s in self._sessions.values():
            out.append({
                "id": s.id,
                "url": s.url,
                "started_at": s.started_at,
                "last_action_at": s.last_action_at,
                "action_count": s.action_count,
                "closed": s.closed,
                "errors": list(s.errors),
            })
        return out


@lru_cache(maxsize=1)
def get_browser_control_service() -> BrowserControlService:
    return BrowserControlService()
