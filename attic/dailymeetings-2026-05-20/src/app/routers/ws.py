"""WebSocket endpoints for real-time recording status, processing progress, and live transcription."""

import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import structlog

from app.services.recording_service import get_recording_status

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.websocket("/ws/meeting-recording")
async def meeting_recording_ws(websocket: WebSocket):
    await websocket.accept()
    logger.debug("meeting_recording_ws_connected")
    try:
        while True:
            status = get_recording_status()
            await websocket.send_text(json.dumps(status))
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        logger.debug("meeting_recording_ws_disconnected")
    except Exception as e:
        logger.error("meeting_recording_ws_error", error=str(e), error_type=type(e).__name__)


@router.websocket("/ws/meeting-processing")
async def meeting_processing_ws(websocket: WebSocket):
    await websocket.accept()
    logger.debug("meeting_processing_ws_connected")
    from app.services.processing_pipeline import register_processing_ws, unregister_processing_ws
    register_processing_ws(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.debug("meeting_processing_ws_disconnected")
        unregister_processing_ws(websocket)
    except Exception as e:
        logger.error("meeting_processing_ws_error", error=str(e), error_type=type(e).__name__)
        unregister_processing_ws(websocket)


@router.websocket("/ws/meeting-live-transcript")
async def meeting_live_transcript_ws(websocket: WebSocket):
    await websocket.accept()
    logger.debug("meeting_live_transcript_ws_connected")
    from app.services.live_transcription_service import register_live_ws, unregister_live_ws
    register_live_ws(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.debug("meeting_live_transcript_ws_disconnected")
        unregister_live_ws(websocket)
    except Exception as e:
        logger.error("meeting_live_transcript_ws_error", error=str(e), error_type=type(e).__name__)
        unregister_live_ws(websocket)
