"""Application settings, loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # --- Core ---
    app_name: str = "NewNews"
    environment: str = "development"
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"

    # --- Database ---
    database_url: str = "postgresql+psycopg://newnews:newnews@localhost:5432/newnews"

    # --- Auth ---
    admin_api_key: str = "change-me-admin"

    # --- AI provider ---
    ai_provider: str = "stub"  # "stub" | "groq"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_stt_model: str = "whisper-large-v3"

    # --- Pipeline tuning ---
    credibility_verified_threshold: float = 0.75
    credibility_review_threshold: float = 0.45
    neardup_threshold: float = 0.85
    neardup_suspect_threshold: float = 0.6
    neardup_window_days: int = 90
    neardup_candidate_limit: int = 2000
    worker_poll_interval_ms: int = 200
    sse_poll_interval_ms: int = 200
    heartbeat_interval_s: float = 15.0
    job_max_attempts: int = 3
    job_retry_base_seconds: int = 5

    # --- Storage ---
    media_root: str = "/data/media"

    @property
    def sse_poll_interval_s(self) -> float:
        return self.sse_poll_interval_ms / 1000.0

    @property
    def worker_poll_interval_s(self) -> float:
        return self.worker_poll_interval_ms / 1000.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
