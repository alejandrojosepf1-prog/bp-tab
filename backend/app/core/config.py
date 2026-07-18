from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application configuration, sourced from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_name: str = "BP Tab Betting"
    environment: str = "development"
    debug: bool = False

    # --- Database ---
    database_url: str = "postgresql+asyncpg://bp:bp@localhost:5432/bp_tab"

    # --- Redis / Celery ---
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # --- Auth ---
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 12

    # --- Scraper ---
    scrape_interval_seconds: int = 60
    scraper_user_agent: str = "BPTabBettingBot/0.1 (+https://github.com/; contact: admin)"
    scraper_request_timeout_seconds: float = 15.0
    scraper_min_delay_seconds: float = 0.5

    # --- CORS ---
    cors_allowed_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
