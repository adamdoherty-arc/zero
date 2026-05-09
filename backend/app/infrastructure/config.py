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

    # Local LLM backend — vLLM only (Ollama retired ecosystem-wide 2026-04-27).
    # Field kept for backwards-compat with code that reads it; value is locked
    # to "vllm". Cloud providers (Gemini, Kimi, OpenRouter, MiniMax, HuggingFace)
    # are unaffected and route via shared-litellm at :4444.
    local_llm_backend: str = "vllm"

    # vLLM Settings (pinned local backend — shared containers from shared-infra)
    vllm_chat_url: str = "http://localhost:18800/v1"
    vllm_chat_base_url: str = "http://localhost:18800/v1"
    vllm_chat_model: str = "qwen3-chat"
    vllm_embed_url: str = "http://localhost:8001/v1"
    vllm_embed_base_url: str = "http://localhost:8001/v1"
    vllm_embed_model: str = "Qwen/Qwen3-Embedding-0.6B"
    vllm_api_key: str = "EMPTY"
    vllm_timeout: int = 600
    embed_provider: str = "vllm"  # vLLM only post-2026-04-27

    # Legion Sprint Manager
    # Use host.docker.internal for Docker environments, localhost for local development
    legion_api_url: str = "http://host.docker.internal:8005"
    legion_api_prefix: str = "/api"
    legion_timeout: int = 30
    zero_legion_project_id: int = 8  # Zero's project ID in Legion

    # Cross-project codebase access
    projects_root: str = "/projects"  # Root dir for mounted project codebases

    # Obsidian vault (personal second brain) — host C:\code\vault\ObsidianZero, mounted at /vault
    vault_path: str = "/vault"
    vault_agent_research_subdir: str = "00_Meta/_agent/research"
    vault_daily_subdir: str = "20_Calendar/Daily"

    # Autonomous research loop
    autonomous_research_enabled: bool = True
    autonomous_research_interval_minutes: int = 15
    autonomous_research_max_concurrent: int = 2
    autonomous_research_topic_cooldown_hours: int = 6  # don't re-research a topic within N hours
    autonomous_research_daily_budget_usd: float = 2.0

    # SecondBrain Phase 4+ controls
    # dry_run replaces every external-side-effect MCP tool with a mock. Used the first
    # 72h when turning on a new capability. Toggle via ZERO_DRY_RUN=true.
    dry_run: bool = False
    # Attention economy (SecondBrain §6).
    dnd_start_hour: int = 22      # local hour: DND begins
    dnd_end_hour: int = 7          # local hour: DND ends
    max_interrupts_per_day: int = 5
    min_interrupt_salience: float = 0.6  # alerts below this batch into morning digest

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

    # Embedding Settings (for RAG / semantic search). vLLM is the default
    # provider; the embedding client truncates Qwen3-Embedding vectors to this
    # dimension for older 768-dim pgvector tables.
    embedding_model: str = "qwen3-embed"
    embedding_dimension: int = 768

    # Reachy Mini voice surface
    reachy_api_url: str = "http://host.docker.internal:8000"
    reachy_tts_confirmations: bool = True  # speak "Recording started" / "Meeting saved"
    # Ambient camera understanding is useful when explicitly enabled, but the
    # VLM tick can take many seconds and should not compete with live voice by
    # default. Enable with ZERO_AMBIENT_VISION_ENABLED=true.
    ambient_vision_enabled: bool = False

    # Reachy realtime voice chat (ported from reachy_mini_conversation_app).
    # Two provider backends — OpenAI Realtime and Gemini Live — each BYO API key.
    # openai_api_key is net-new to Zero (no other service needs OpenAI directly;
    # the existing openai SDK usage is for OpenAI-compatible endpoints).
    openai_api_key: Optional[str] = None
    reachy_realtime_backend: Optional[str] = None  # explicit override: "local", "openai", or "gemini"
    reachy_realtime_model: Optional[str] = None  # None = default for chosen backend
    reachy_realtime_voice: Optional[str] = None  # None = default for chosen backend
    reachy_realtime_profile: Optional[str] = None  # profile / persona id, None = default
    # The "local" realtime backend talks to vLLM via the existing
    # ``vllm_chat_url`` setting at the top of this class.

    # Meeting recording: preferred mic device for Reachy/other USB capture. Matched
    # as a case-insensitive substring against sounddevice.query_devices() names.
    preferred_mic_device_name: Optional[str] = None
    # URL of the Zero Host Audio Agent (outside Docker) that actually records audio.
    # Resolves to ZERO_HOST_AGENT_URL via the Settings env_prefix. When unset, the
    # backend falls back to its in-process audio capture (only works if the backend
    # itself is running on the host with pyaudiowpatch/sounddevice installed).
    host_agent_url: Optional[str] = None

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
    # Plural form — comma-separated keys. Carousel V2 free-tier rotation
    # pool multiplies throughput across multiple OpenRouter accounts. Falls
    # back to ``[openrouter_api_key]`` when this is empty.
    openrouter_api_keys: str = ""
    huggingface_api_key: Optional[str] = None
    kimi_api_key: Optional[str] = None
    kimi_base_url: str = "https://api.moonshot.ai/v1"
    # Kimi multimodal model used by Stage-8 image verification. Moonshot's
    # public chat-completions API doesn't yet expose a stable vision SKU,
    # so the carousel V2 router currently routes Stage 8 through Gemini Flash
    # (Tier 0) + OpenRouter free pool (Tier 1). When Moonshot ships a public
    # vision alias, set ZERO_KIMI_VISION_MODEL to enable it as an extra tier.
    kimi_vision_model: str = "moonshot-v1-8k-vision-preview"

    # ----- Stage-8 VLM budget caps (carousel V2 cheap-VLM router) -----------
    # Daily ceiling on PAID VLM spend. Free-tier OpenRouter calls are exempt.
    # When the daily total would exceed this, paid tiers (Gemini) are skipped
    # and the router falls through to free pool / failure-soft no-VLM ranking.
    vlm_daily_budget_usd: float = 1.0
    # Per-carousel ceiling — prevents one runaway generation from eating the
    # whole daily budget. Defaults to ~10% of the daily cap.
    vlm_per_carousel_cap_usd: float = 0.10
    minimax_api_key: Optional[str] = None
    minimax_base_url: str = "https://api.minimax.io/v1"

    # TMDB (The Movie Database) - free API for movie/TV images
    tmdp_api_key: Optional[str] = None
    tmdp_read_access_token: Optional[str] = None

    # Free image APIs (Pexels, Unsplash, Pixabay)
    pexels_api_key: Optional[str] = None
    unsplash_access_key: Optional[str] = None
    pixabay_api_key: Optional[str] = None

    # Additional image sources
    flickr_api_key: Optional[str] = None
    giphy_api_key: Optional[str] = None
    omdb_api_key: Optional[str] = None
    reddit_client_id: Optional[str] = None
    reddit_client_secret: Optional[str] = None
    deviantart_client_id: Optional[str] = None
    deviantart_client_secret: Optional[str] = None

    # Niche character image APIs
    comicvine_api_key: Optional[str] = None
    fanart_api_key: Optional[str] = None
    thetvdb_api_key: Optional[str] = None
    giant_bomb_api_key: Optional[str] = None
    superhero_api_key: Optional[str] = None
    # Reddit / IMDb (carosel.txt Phase 2 image curation)
    reddit_user_agent: str = "zero-carousel/1.0"
    imdb_graphql_user_agent: str = "zero-carousel/1.0"

    # ----- Carousel V2 infrastructure plane (carosel.txt blueprint Phase 1) -----
    use_temporal: bool = False  # ZERO_USE_TEMPORAL — flips Temporal-routed traffic on
    temporal_host: str = "zero-temporal:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "carousel-default"
    temporal_max_activities: int = 8
    temporal_max_workflows: int = 16

    redis_url: str = "redis://zero-redis:6379/0"
    qdrant_url: str = "http://zero-qdrant:6333"
    qdrant_grpc_port: int = 6334

    minio_endpoint: str = "http://zero-minio:9000"
    minio_access_key: str = "zero-minio"
    minio_secret_key: str = "zero-minio-change-me"
    minio_bucket_carousel: str = "zero-carousel"
    minio_bucket_sources: str = "zero-image-sources"

    # Cloudflare R2 — production target for TikTok PULL_FROM_URL.
    r2_account_id: Optional[str] = None
    r2_access_key: Optional[str] = None
    r2_secret_key: Optional[str] = None
    r2_bucket: Optional[str] = None
    r2_public_domain: Optional[str] = None  # verified domain in TikTok dev portal

    langfuse_host: str = "http://zero-langfuse-web:3000"
    langfuse_public_key: Optional[str] = None
    langfuse_secret_key: Optional[str] = None

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
    ollama_concurrency: int = 2
    # Ollama HTTP fallback. Used by ollama_client.py for legacy embed/chat
    # paths and as the dense-vector source for vault retrieval. Routes via
    # host.docker.internal in Docker; localhost on host. ZERO_OLLAMA_BASE_URL
    # in env wins. Without these fields, every dense vault search raised
    # AttributeError("'Settings' object has no attribute 'ollama_base_url'").
    ollama_base_url: str = "http://host.docker.internal:11434/v1"
    ollama_model: str = "qwen3-chat"
    ollama_timeout: int = 900

    # Autonomous content loop (migration 035 / orchestration hardening W2)
    # When true, scheduler job autonomous_content_loop drives carousel generation
    # off unprocessed TrendingSignalModel rows every 30 minutes.
    autonomous_content_enabled: bool = False
    # Rubric gate threshold for the W3 fail-retry loop on carousel generation.
    carousel_rubric_threshold: float = 6.5
    carousel_rubric_max_retries: int = 2

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
    auto_create_tasks_from_meetings: bool = False
    auto_record_all: bool = False

    class Config:
        env_file = ".env"
        env_prefix = "ZERO_"
        extra = "ignore"


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
