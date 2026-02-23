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
    ollama_model: str = "qwen3-coder-next:latest"
    ollama_timeout: int = 300

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
    embedding_model: str = "nomic-embed-text"
    embedding_dimension: int = 768

    # AIContentTools Integration
    ai_content_tools_url: str = "http://host.docker.internal:8085"

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

    # LLM Cost Control
    llm_daily_budget_usd: float = 5.0

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
