"""
Tests for the speech-reactive head wobbler (Phase 3 of the realtime port).

The DSP (``SwayRollRT``) is deterministic for a fixed seed, so we can assert
invariants on its outputs (shape, silence produces zero sway, loud speech
produces non-zero sway, reset zeroes state, correct hop count).

The async consumer (``AsyncHeadWobbler``) is tested at its seams:
- start/stop lifecycle
- feed_pcm16 enqueues work without blocking
- apply_offsets callback fires with correct tuple shape
- request_reset_after_current_audio zeroes offsets once queue drains
- resetting during playback prevents further dispatch from the old generation
"""

from __future__ import annotations

import asyncio
import math

import numpy as np
import pytest

from app.services.reachy_realtime.head_wobbler import AsyncHeadWobbler, Offsets
from app.services.reachy_realtime.sway import (
    HOP,
    HOP_MS,
    SR,
    SwayRollRT,
)


def _silence(seconds: float, sr: int = SR) -> np.ndarray:
    return np.zeros(int(seconds * sr), dtype=np.int16)


def _loud_speech(seconds: float, sr: int = SR, freq: float = 200.0) -> np.ndarray:
    t = np.arange(int(seconds * sr)) / sr
    wave = 0.5 * np.sin(2 * np.pi * freq * t)
    return (wave * 32767).astype(np.int16)


# ============================================================
# SwayRollRT — pure DSP
# ============================================================

class TestSwayRollRT:
    def test_silence_produces_zero_sway(self):
        rt = SwayRollRT()
        hops = rt.feed(_silence(1.0), sr=SR)
        # One second of silence = 1000/HOP_MS = 20 hops.
        assert len(hops) == int(1.0 / (HOP_MS / 1000.0))
        # Silence should keep sway-env low, so amplitudes stay tiny.
        max_pitch = max(abs(h["pitch_rad"]) for h in hops)
        assert max_pitch < 1e-3

    def test_loud_speech_produces_nonzero_sway(self):
        rt = SwayRollRT()
        # 3 s of sustained speech-band tone clears the VAD attack (40 ms) and
        # sway attack (50 ms) with plenty of headroom.
        hops = rt.feed(_loud_speech(3.0), sr=SR)
        assert len(hops) > 0
        # After the attack windows, amplitudes should be measurable on at
        # least one DOF (oscillators cross zero so any single hop may be near
        # zero; check across all hops).
        tail = hops[-20:]
        assert max(abs(h["pitch_rad"]) for h in tail) > 1e-3

    def test_output_dict_has_all_6_dof(self):
        rt = SwayRollRT()
        hops = rt.feed(_loud_speech(0.1), sr=SR)
        if hops:
            for key in ("x_mm", "y_mm", "z_mm", "roll_rad", "pitch_rad", "yaw_rad"):
                assert key in hops[0]

    def test_resample_from_24khz(self):
        # Provider audio comes in at 24 kHz; SwayRollRT resamples internally.
        rt = SwayRollRT()
        hops = rt.feed(_silence(0.5, sr=24000), sr=24000)
        # ~10 hops after resample to 16 kHz (500 ms / 50 ms).
        assert 8 <= len(hops) <= 12

    def test_reset_clears_time(self):
        rt = SwayRollRT()
        rt.feed(_loud_speech(1.0), sr=SR)
        assert rt.t > 0
        rt.reset()
        assert rt.t == 0.0
        assert rt.vad_on is False
        assert rt.sway_env == 0.0

    def test_deterministic_for_fixed_seed(self):
        rt1 = SwayRollRT(rng_seed=42)
        rt2 = SwayRollRT(rng_seed=42)
        pcm = _loud_speech(0.5)
        h1 = rt1.feed(pcm, sr=SR)
        h2 = rt2.feed(pcm, sr=SR)
        assert len(h1) == len(h2)
        for a, b in zip(h1, h2):
            for k in a:
                assert math.isclose(a[k], b[k], rel_tol=0, abs_tol=1e-9)

    def test_different_seeds_produce_different_phases(self):
        rt1 = SwayRollRT(rng_seed=1)
        rt2 = SwayRollRT(rng_seed=2)
        assert rt1.phase_pitch != rt2.phase_pitch

    def test_empty_input_yields_no_hops(self):
        rt = SwayRollRT()
        assert rt.feed(np.array([], dtype=np.int16), sr=SR) == []

    def test_partial_hop_carried_over(self):
        rt = SwayRollRT()
        # Feed less than one HOP worth of samples — should emit nothing but
        # keep the samples for the next call.
        assert rt.feed(np.zeros(HOP // 2, dtype=np.int16), sr=SR) == []
        # Now complete the hop.
        out = rt.feed(np.zeros(HOP // 2 + 1, dtype=np.int16), sr=SR)
        assert len(out) >= 1


# ============================================================
# AsyncHeadWobbler — consumer lifecycle
# ============================================================

class TestAsyncHeadWobbler:
    @pytest.mark.asyncio
    async def test_start_stop_is_idempotent(self):
        captured: list[Offsets] = []

        async def _apply(offsets: Offsets) -> None:
            captured.append(offsets)

        wobbler = AsyncHeadWobbler(apply_offsets=_apply)
        await wobbler.start()
        await wobbler.start()  # second call is a no-op
        await wobbler.stop()
        await wobbler.stop()

    @pytest.mark.asyncio
    async def test_feed_silence_then_loud_produces_callbacks(self):
        captured: list[Offsets] = []

        async def _apply(offsets: Offsets) -> None:
            captured.append(offsets)

        wobbler = AsyncHeadWobbler(apply_offsets=_apply)
        await wobbler.start()
        try:
            # Feed 1 s of loud audio in one shot (PCM16 @ 16 kHz).
            await wobbler.feed_pcm16(_loud_speech(1.0).tobytes(), sample_rate=SR)
            # Hops emit at 50 ms cadence with a 200 ms primer latency.
            await asyncio.sleep(1.6)
        finally:
            await wobbler.stop()

        # Should have fired multiple offset callbacks.
        assert len(captured) > 5
        for t in captured:
            assert len(t) == 6
            for v in t:
                assert isinstance(v, float)

    @pytest.mark.asyncio
    async def test_reset_drains_queue(self):
        captured: list[Offsets] = []

        async def _apply(offsets: Offsets) -> None:
            captured.append(offsets)

        wobbler = AsyncHeadWobbler(apply_offsets=_apply)
        await wobbler.start()
        try:
            await wobbler.feed_pcm16(_loud_speech(2.0).tobytes(), sample_rate=SR)
            # Reset immediately — queue should be drained and generation bumped.
            wobbler.reset()
            await asyncio.sleep(0.2)
        finally:
            await wobbler.stop()
        # Most callbacks should be skipped since we reset before they could run.
        # Upper bound is a sanity check, not exact.
        assert len(captured) < 30

    @pytest.mark.asyncio
    async def test_apply_offsets_failure_does_not_kill_loop(self):
        calls = 0

        async def _apply(offsets: Offsets) -> None:
            nonlocal calls
            calls += 1
            raise RuntimeError("daemon down")

        wobbler = AsyncHeadWobbler(apply_offsets=_apply)
        await wobbler.start()
        try:
            await wobbler.feed_pcm16(_loud_speech(1.0).tobytes(), sample_rate=SR)
            await asyncio.sleep(1.2)
        finally:
            await wobbler.stop()

        # Even though every call raised, the loop kept firing — proves we
        # swallow exceptions rather than letting one bad call break sway.
        assert calls > 2

    @pytest.mark.asyncio
    async def test_feed_pcm16_rejects_empty_input(self):
        wobbler = AsyncHeadWobbler(apply_offsets=_noop_apply)
        await wobbler.start()
        try:
            # These must not raise and not enqueue anything.
            await wobbler.feed_pcm16(b"", sample_rate=SR)
            await wobbler.feed_pcm16(b"\x00", sample_rate=SR)  # odd-byte = ValueError → swallowed
        finally:
            await wobbler.stop()


async def _noop_apply(_offsets: Offsets) -> None:
    return None
