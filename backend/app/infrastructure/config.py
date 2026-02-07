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

    # LLM Settings (Ollama)
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen3:32b"
    ollama_timeout: int = 60

    # Legion Sprint Manager
    # Use host.docker.internal for Docker environments, localhost for local development
    legion_api_url: str = "http://host.docker.internal:8005"
    legion_api_prefix: str = "/api"
    legion_timeout: int = 30

    # SearXNG (Web Search)
    # Use container name for Docker, localhost:8888 for local development
    searxng_url: str = "http://zero-searxng:8080"

    # PostgreSQL for LangGraph checkpointing (optional)
    # Format: postgresql://user:pass@host:5433/dbname
    postgres_url: Optional[str] = None

    # CORS
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

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
