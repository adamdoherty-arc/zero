"""
Async speech-reactive head wobbler — port of
``reachy_mini_conversation_app.audio.head_wobbler.HeadWobbler``.

Upstream runs a Python thread that drains a queue of PCM audio and drives an
in-process MovementManager via additive offsets, letting primary moves (dance,
emotion, goto) compose with the continuous sway. Zero has no in-process motion
manager — motion goes through ``reachy_service`` to the daemon — so this port
is a simpler asyncio consumer that invokes a caller-supplied
``apply_offsets`` coroutine with the DSP output.

Why async + no thread: the DSP is O(~hop samples) per call (tens of µs on
float32 numpy), well within the tolerance of running on the event loop. No
need for the extra plumbing that comes with spawning another thread.

Expected use inside the realtime session:

    wobbler = AsyncHeadWobbler(apply_offsets=call_daemon_set_target)
    await wobbler.start()
    # then, in the OpenAI / Gemini handler's audio.delta branch:
    await wobbler.feed_pcm16(pcm_bytes, sample_rate=24000)
    # … at turn end:
    wobbler.request_reset_after_current_audio()
    # on session close:
    await wobbler.stop()
"""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Tuple

import numpy as np
import structlog

from app.services.reachy_realtime.sway import HOP_MS, SwayRollRT

logger = structlog.get_logger()

MOVEMENT_LATENCY_S = 0.2

Offsets = Tuple[float, float, float, float, float, float]  # x_m, y_m, z_m, roll, pitch, yaw
ApplyOffsets = Callable[[Offsets], Awaitable[None]]


class AsyncHeadWobbler:
    """asyncio wrapper around ``SwayRollRT`` that emits offsets at hop cadence."""

    HOP_DT = HOP_MS / 1000.0

    def __init__(self, apply_offsets: ApplyOffsets) -> None:
        self._apply_offsets = apply_offsets
        self._queue: asyncio.Queue[tuple[int, int, np.ndarray, float]] = asyncio.Queue()
        self._sway = SwayRollRT()
        self._generation = 0
        self._base_ts: float | None = None
        self._hops_done = 0
        self._reset_after_audio = False
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    # ---- public API ----

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="reachy-head-wobbler")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        await self._apply_zero()

    async def feed_pcm16(
        self,
        pcm_bytes: bytes,
        sample_rate: int,
        start_delay_s: float = 0.0,
    ) -> None:
        """Enqueue PCM16 little-endian audio for the sway DSP.

        Called from each provider-output audio.delta. Never blocks the caller.
        """
        if not pcm_bytes:
            return
        try:
            arr = np.frombuffer(pcm_bytes, dtype=np.int16)
        except ValueError:
            return
        if arr.size == 0:
            return
        self._reset_after_audio = False
        await self._queue.put((self._generation, int(sample_rate), arr, max(0.0, start_delay_s)))

    def request_reset_after_current_audio(self) -> None:
        """Mark 'when the queue drains, zero out offsets and reset sway state'."""
        self._reset_after_audio = True

    def reset(self) -> None:
        self._generation += 1
        self._base_ts = None
        self._hops_done = 0
        self._reset_after_audio = False
        self._sway.reset()
        # Drain queue without waiting.
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break

    # ---- internal consumer ----

    async def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    gen, sr, pcm, start_delay = await asyncio.wait_for(
                        self._queue.get(), timeout=self.HOP_DT,
                    )
                except asyncio.TimeoutError:
                    if self._should_reset_after_audio():
                        await self._apply_zero()
                        self.reset()
                    continue

                if gen != self._generation:
                    continue
                if self._base_ts is None:
                    self._base_ts = time.monotonic() + start_delay

                results = self._sway.feed(pcm, sr)

                for i, r in enumerate(results):
                    if self._stop.is_set() or gen != self._generation:
                        break
                    target = (self._base_ts or time.monotonic()) + MOVEMENT_LATENCY_S + self._hops_done * self.HOP_DT
                    now = time.monotonic()
                    if now - target >= self.HOP_DT:
                        # Too far behind — skip one hop to catch up (matches upstream).
                        self._hops_done += 1
                        continue
                    if target > now:
                        await asyncio.sleep(target - now)
                    if self._stop.is_set() or gen != self._generation:
                        break
                    offsets: Offsets = (
                        r["x_mm"] / 1000.0,
                        r["y_mm"] / 1000.0,
                        r["z_mm"] / 1000.0,
                        r["roll_rad"],
                        r["pitch_rad"],
                        r["yaw_rad"],
                    )
                    try:
                        await self._apply_offsets(offsets)
                    except Exception as e:  # never let a daemon error kill the loop
                        logger.debug("head_wobbler_apply_failed", error=str(e))
                    self._hops_done += 1
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("head_wobbler_loop_crashed")

    async def _apply_zero(self) -> None:
        try:
            await self._apply_offsets((0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
        except Exception as e:
            logger.debug("head_wobbler_zero_apply_failed", error=str(e))

    def _should_reset_after_audio(self) -> bool:
        if not self._reset_after_audio or self._base_ts is None:
            return False
        if not self._queue.empty():
            return False
        reset_at = self._base_ts + MOVEMENT_LATENCY_S + self._hops_done * self.HOP_DT
        return time.monotonic() >= reset_at
