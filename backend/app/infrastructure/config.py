"""
Configuration management for ZERO API.
"""

from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Optional
import os


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    # Paths
    workspace_dir: str = "../workspace"
    config_dir: str = "../config"

    # API Settings
    api_host: str = "0.0.0.0"
    api_port: int = 18792

    # LLM Settings (Ollama) — fallback only; LLM router is source of truth
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen3.6:35b-a3b-q8_0"
    ollama_timeout: int = 900

    # Legion Sprint Manager
    # Use host.docker.internal for Docker environments, localhost for local development
    legion_api_url: str = "http://host.docker.internal:8005"
    legion_api_prefix: str = "/api"
    legion_timeout: int = 30
    zero_legion_project_id: int = 8  # Zero's project ID in Legion

    # Cross-project codebase access
    projects_root: str = "/projects"  # Root dir for mounted project codebases

    # SearXNG (Web Search)
    # Use container name for Docker, localhost:8888 for local development
    searxng_url: str = "http://zero-searxng:8080"

    # PostgreSQL Database
    postgres_url: str = "postgresql://zero:zero_dev@zero-postgres:5432/zero"

    # CORS
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # Google OAuth
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    google_redirect_uri: str = "http://localhost:18792/api/google/auth/callback"
    frontend_url: str = "http://localhost:5173"

    # Email Automation
    email_automation_enabled: bool = True
    email_automation_check_interval: int = 300  # 5 minutes
    email_classifier_model: str = "distilbert-base-uncased-finetuned-sst-2-english"
    email_automation_confidence_threshold: float = 0.85
    email_question_timeout_hours: int = 24

    # Embedding Settings (for RAG / semantic search)
    embedding_model: str = "nomic-embed-text-v2-moe"
    embedding_dimension: int = 768

    # AIContentTools Integration
    ai_content_tools_url: str = "http://host.docker.internal:8085"

    # Firecrawl (Web Scraping) — runs in ADA stack, shared via ada-bridge network
    firecrawl_url: str = "http://ada-firecrawl:3002"

    # Notion Integration
    notion_api_key: Optional[str] = None
    notion_database_id: Optional[str] = None
    notion_workspace_page_id: Optional[str] = None

    # ADA Bridge (Prediction Market data push)
    ada_api_url: str = "http://ada-backend:8003"
    ada_api_token: Optional[str] = None

    # Kalshi API
    kalshi_api_url: str = "https://api.elections.kalshi.com/trade-api/v2"
    kalshi_api_key: Optional[str] = None
    kalshi_api_secret: Optional[str] = None

    # Polymarket API
    polymarket_gamma_url: str = "https://gamma-api.polymarket.com"

    # Multi-Provider LLM API Keys
    gemini_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    huggingface_api_key: Optional[str] = None
    kimi_api_key: Optional[str] = None
    kimi_base_url: str = "https://api.moonshot.ai/v1"
    minimax_api_key: Optional[str] = None
    minimax_base_url: str = "https://api.minimax.io/v1"

    # TMDB (The Movie Database) - free API for movie/TV images
    tmdp_api_key: Optional[str] = None
    tmdp_read_access_token: Optional[str] = None

    # Free image APIs (Pexels, Unsplash, Pixabay)
    pexels_api_key: Optional[str] = None
    unsplash_access_key: Optional[str] = None
    pixabay_api_key: Optional[str] = None

    # TikTok Content Posting API
    tiktok_client_key: Optional[str] = None
    tiktok_client_secret: Optional[str] = None
    tiktok_redirect_uri: str = "http://localhost:18792/api/tiktok-shop/auth/callback"

    # LLM Cost Control
    llm_daily_budget_usd: float = 5.0

    # Character Content Autopilot
    character_autopilot_enabled: bool = True
    character_minimax_daily_cap_usd: float = 3.50
    character_minimax_min_stage2_score: float = 80.0
    character_auto_approve_threshold: float = 85.0
    character_discovery_enabled: bool = True
    character_discovery_daily_cap: int = 20

    # Meeting Intelligence (DailyMemory)
    whisper_model_size: str = "large-v3"
    whisper_device: str = "cuda"
    whisper_compute_type: str = "float16"
    whisper_language: str = "en"
    hf_token: Optional[str] = None  # HuggingFace token for pyannote diarization
    diarization_model: str = "pyannote/speaker-diarization-3.1"
    max_speakers: int = 10
    recordings_dir: str = "../workspace/recordings"
    audio_source: str = "mixed"  # system|mic|mixed
    sample_rate: int = 16000
    auto_record_meetings: bool = False

    class Config:
        env_file = ".env"
        env_prefix = "ZERO_"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


def get_workspace_path(subpath: str = "") -> Path:
    """Get absolute path within workspace directory."""
    settings = get_settings()
    base = Path(settings.workspace_dir).resolve()
    if subpath:
        return base / subpath
    return base


def get_sprints_path() -> Path:
    """Get path to sprints data directory."""
    return get_workspace_path("sprints")


def get_enhancement_path() -> Path:
    """Get path to enhancement data directory."""
    return get_workspace_path("enhancement")


def get_money_maker_path() -> Path:
    """Get path to money-maker data directory."""
    return get_workspace_path("money-maker")


def get_ecosystem_path() -> Path:
    """Get path to ecosystem data directory."""
    return get_workspace_path("ecosystem")


def get_recordings_path() -> Path:
    """Get path to meeting recordings directory."""
    settings = get_settings()
    return Path(settings.recordings_dir).resolve()
