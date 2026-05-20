"""Configuration for DailyMeetings standalone app."""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    # Database
    postgres_url: str = "postgresql://zero:zero_dev@localhost:5433/zero"

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3-coder-next:latest"
    ollama_timeout: int = 300

    # Whisper transcription (pipeline — runs after recording stops)
    whisper_model_size: str = "small"
    whisper_device: str = "auto"
    whisper_compute_type: str = "int8"
    whisper_language: str = "en"

    # Live transcription (fast model, runs during recording)
    live_whisper_model_size: str = "base"

    # Speaker diarization
    hf_token: Optional[str] = None
    diarization_model: str = "pyannote/speaker-diarization-3.1"
    max_speakers: int = 10

    # Audio
    recordings_dir: str = "./recordings"
    audio_source: str = "mixed"  # system|mic|mixed
    sample_rate: int = 16000

    # Embedding
    embedding_model: str = "nomic-embed-text-v2-moe"
    embedding_dimension: int = 768

    # Server
    api_host: str = "0.0.0.0"
    api_port: int = 18793

    # CORS
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    class Config:
        env_file = ".env"
        env_prefix = "DM_"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


def get_recordings_path() -> Path:
    settings = get_settings()
    return Path(settings.recordings_dir).resolve()
