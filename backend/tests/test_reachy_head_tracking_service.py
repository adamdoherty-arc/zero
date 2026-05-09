from __future__ import annotations

import asyncio
import time

import pytest

from app.services.reachy_head_tracking_service import ReachyHeadTrackingService


def test_rejects_tiny_face_false_positives():
    service = ReachyHeadTrackingService()

    assert service._is_usable_face({"width": 0.034, "height": 0.06}) is False
    assert service._is_usable_face({"width": 0.08, "height": 0.08}) is True


@pytest.mark.asyncio
async def test_status_reverts_to_scanning_when_latest_scan_loses_face():
    service = ReachyHeadTrackingService()
    service._task = asyncio.create_task(asyncio.sleep(10))
    service._last_detection = {"kind": "face", "width": 0.1, "height": 0.1}
    service._last_error = None
    service._last_move_at = time.time()

    try:
        assert service.status()["state"] == "tracking"

        service._last_detection = None
        service._last_error = "No usable face detected in the current Reachy camera frame."

        status = service.status()
        assert status["state"] == "scanning"
        assert "No usable face" in status["detail"]
    finally:
        service._task.cancel()
        try:
            await service._task
        except asyncio.CancelledError:
            pass
