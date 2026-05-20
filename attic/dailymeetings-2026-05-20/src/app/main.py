"""DailyMeetings - Standalone Meeting Intelligence App.

Runs on Windows host for audio capture (WASAPI loopback + microphone).
Connects to the same PostgreSQL used by Zero (port 5433 on host).
Uses Ollama for transcription summarization and embeddings.
"""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_database, close_database, create_tables

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("dailymeetings_starting", port=settings.api_port)

    # Initialize database
    await init_database(settings.postgres_url)
    await create_tables()
    logger.info("database_ready")

    yield

    # Shutdown
    from app.ollama_client import get_ollama_client
    client = get_ollama_client()
    await client.close()
    await close_database()
    logger.info("dailymeetings_stopped")


app = FastAPI(
    title="DailyMeetings",
    description="Standalone meeting recording, transcription, and intelligence",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers
from app.routers import meetings, recordings, transcriptions, summaries, search, chat, speakers, ws

app.include_router(meetings.router, prefix="/api/meetings", tags=["meetings"])
app.include_router(recordings.router, prefix="/api/meeting-recordings", tags=["recordings"])
app.include_router(transcriptions.router, prefix="/api/meeting-transcriptions", tags=["transcriptions"])
app.include_router(summaries.router, prefix="/api/meeting-summaries", tags=["summaries"])
app.include_router(search.router, prefix="/api/meeting-search", tags=["search"])
app.include_router(chat.router, prefix="/api/meeting-chat", tags=["chat"])
app.include_router(speakers.router, prefix="/api/meetings", tags=["speakers"])
app.include_router(ws.router, tags=["websocket"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "DailyMeetings"}


