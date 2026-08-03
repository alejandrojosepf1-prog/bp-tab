from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application configuration, sourced from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_name: str = "Claim"
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
    # How often active tournaments are re-scraped. 180s keeps markets and settlement fresh (a
    # debate round takes far longer than that to produce results) without hammering someone
    # else's Tabbycat instance.
    scrape_interval_seconds: int = 180
    # Run the in-process periodic scraper (app.tasks.autoscrape) from the API process itself.
    # This is what makes auto-updating work on the Render+Neon deployment, which has no Celery
    # broker -- set to false if a real Celery beat process is ever deployed, so the two can't
    # both scrape the same tournament.
    autoscrape_enabled: bool = True
    # Grace period before the first cycle, so a deploy/cold-start doesn't immediately re-scrape.
    autoscrape_startup_delay_seconds: int = 20
    scraper_user_agent: str = "BPTabBettingBot/0.1 (+https://github.com/; contact: admin)"
    scraper_request_timeout_seconds: float = 15.0
    scraper_min_delay_seconds: float = 0.5

    # --- CORS ---
    cors_allowed_origins: list[str] = ["http://localhost:3000"]
    # Every Vercel deploy gets a NEW unique per-deployment alias (e.g.
    # claim-<hash>-<team>.vercel.app) on top of the stable production domain already in
    # cors_allowed_origins -- hardcoding one exact alias breaks again on the next deploy (see
    # the real incident this fixed: a single mistyped character in one alias 401'd every
    # login). Matches any subdomain of this project on vercel.app instead of the one domain.
    cors_allowed_origin_regex: str | None = r"^https://claim-[a-z0-9-]+\.vercel\.app$"

    # --- Access passes (CNADE 2026 Roadmap Pieza 4) ---
    # Where the activation link in the approval email points -- the SPA route that completes
    # account setup, not the API.
    frontend_base_url: str = "http://localhost:3000"
    # None until Paranoid creates a Resend account and sets this -- see
    # app.services.email_service, which logs the email instead of sending when unset, same
    # "collected but not verified" pragmatism this platform already uses for phone numbers.
    resend_api_key: str | None = None
    resend_from_email: str = "Claim <onboarding@resend.dev>"


@lru_cache
def get_settings() -> Settings:
    return Settings()
