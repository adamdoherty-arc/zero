"""
Background tool manager — long-running tool calls don't block the realtime
conversation. Ported almost verbatim from the upstream
``reachy_mini_conversation_app.tools.background_tool_manager``.

Upstream source:
https://github.com/pollen-robotics/reachy_mini_conversation_app/blob/main/src/reachy_mini_conversation_app/tools/background_tool_manager.py

Changes for Zero:
- Uses Pydantic v2 + structlog (matches Zero's stack).
- Drops the ``ToolCallRoutine`` indirection — tools are resolved directly
  through ``tools.dispatch`` because Zero's registry is static (no dynamic
  file loading, no ``SystemTool`` vs user-tool distinction).
"""

from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, Optional

import structlog
from pydantic import BaseModel, Field, PrivateAttr

logger = structlog.get_logger()


class ToolState(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ToolNotification(BaseModel):
    """Payload for tool completion callbacks."""

    id: str
    tool_name: str
    is_idle_tool_call: bool
    status: ToolState
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class BackgroundTool(ToolNotification):
    started_at: float = Field(default_factory=time.monotonic)
    completed_at: Optional[float] = None
    _task: Optional[asyncio.Task[None]] = PrivateAttr(default=None)

    @property
    def tool_id(self) -> str:
        return f"{self.tool_name}-{self.id}-{self.started_at}"

    def as_notification(self) -> ToolNotification:
        return ToolNotification(
            id=self.id,
            tool_name=self.tool_name,
            is_idle_tool_call=self.is_idle_tool_call,
            status=self.status,
            result=self.result,
            error=self.error,
        )


NotificationCallback = Callable[[ToolNotification], Awaitable[None]]
ToolRoutine = Callable[["BackgroundToolManager"], Awaitable[Dict[str, Any]]]


class BackgroundToolManager:
    """Async executor for non-blocking tool runs."""

    MAX_RUN_SECONDS = 86400.0
    MAX_MEMORY_SECONDS = 3600.0
    CLEANUP_INTERVAL_SECONDS = 300.0

    def __init__(self) -> None:
        self._tools: Dict[str, BackgroundTool] = {}
        self._notification_queue: asyncio.Queue[ToolNotification] = asyncio.Queue()
        self._lifecycle_tasks: list[asyncio.Task[None]] = []

    async def start_tool(
        self,
        *,
        call_id: str,
        tool_name: str,
        routine: ToolRoutine,
        is_idle_tool_call: bool,
    ) -> BackgroundTool:
        bg_tool = BackgroundTool(
            id=call_id,
            tool_name=tool_name,
            is_idle_tool_call=is_idle_tool_call,
            status=ToolState.RUNNING,
        )
        self._tools[bg_tool.tool_id] = bg_tool

        bg_tool._task = asyncio.create_task(
            self._run(bg_tool, routine),
            name=f"bg-{tool_name}-{call_id}",
        )
        logger.info("bg_tool_started", tool=tool_name, call_id=call_id)
        return bg_tool

    async def _run(self, bg_tool: BackgroundTool, routine: ToolRoutine) -> None:
        try:
            result = await routine(self)
        except asyncio.CancelledError:
            bg_tool.status = ToolState.CANCELLED
            bg_tool.completed_at = time.monotonic()
            bg_tool.error = "Tool cancelled"
            await self._notification_queue.put(bg_tool.as_notification())
            raise
        except Exception as e:
            bg_tool.status = ToolState.FAILED
            bg_tool.completed_at = time.monotonic()
            bg_tool.error = f"{type(e).__name__}: {e}"
            logger.exception("bg_tool_failed", tool=bg_tool.tool_name)
            await self._notification_queue.put(bg_tool.as_notification())
            return

        bg_tool.completed_at = time.monotonic()
        err = result.get("error") if isinstance(result, dict) else None
        if err is not None:
            if err == "Tool cancelled":
                bg_tool.status = ToolState.CANCELLED
            else:
                bg_tool.status = ToolState.FAILED
            bg_tool.error = str(err)
        else:
            bg_tool.status = ToolState.COMPLETED
            bg_tool.result = result if isinstance(result, dict) else {"result": result}
        await self._notification_queue.put(bg_tool.as_notification())

    async def cancel_tool(self, tool_id: str) -> bool:
        t = self._tools.get(tool_id)
        if not t or t.status != ToolState.RUNNING or t._task is None:
            return False
        t._task.cancel()
        return True

    async def start_up(self, callbacks: list[NotificationCallback]) -> None:
        async def _listener() -> None:
            while True:
                note = await self._notification_queue.get()
                for cb in callbacks:
                    try:
                        await cb(note)
                    except Exception:
                        logger.exception("bg_tool_callback_failed", tool=note.tool_name)

        async def _cleanup() -> None:
            while True:
                await asyncio.sleep(self.CLEANUP_INTERVAL_SECONDS)
                now = time.monotonic()
                for tid, t in list(self._tools.items()):
                    if t.status == ToolState.RUNNING and (now - t.started_at) > self.MAX_RUN_SECONDS:
                        await self.cancel_tool(tid)
                    elif t.status in (ToolState.COMPLETED, ToolState.FAILED, ToolState.CANCELLED):
                        if t.completed_at and (now - t.completed_at) > self.MAX_MEMORY_SECONDS:
                            self._tools.pop(tid, None)

        self._lifecycle_tasks = [
            asyncio.create_task(_listener(), name="bg-tool-listener"),
            asyncio.create_task(_cleanup(), name="bg-tool-cleanup"),
        ]

    async def shutdown(self) -> None:
        for t in self._lifecycle_tasks:
            t.cancel()
        for t in self._lifecycle_tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._lifecycle_tasks.clear()
        for tid in list(self._tools.keys()):
            await self.cancel_tool(tid)

    def get_tool(self, tool_id: str) -> Optional[BackgroundTool]:
        return self._tools.get(tool_id)

    def get_running_tools(self) -> list[BackgroundTool]:
        return [t for t in self._tools.values() if t.status == ToolState.RUNNING]
