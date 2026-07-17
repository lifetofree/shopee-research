"""Pydantic-settings configuration. Reads from .env (loaded by python-dotenv at process start).

Subsequent tickets will add cookie / DB / generator fields. This bootstrap
ticket only declares the env keys (with safe defaults) so downstream tickets
can `from shopee_th.config import settings` without a fresh import.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-wide configuration.

    Values come from the environment (or a local .env file). All fields are
    optional in the bootstrap ticket so the app can boot without secrets; later
    tickets will tighten validation.
    """

    model_config = SettingsConfigDict(
        env_prefix="SHOPEE_TH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Shopee session (Surface A) ---
    session_cookie: str = Field(
        default="",
        description=(
            "`; `-joined cookie string for shopee.co.th. "
            "Populated by `make refresh-cookie`."
        ),
    )
    user_agent: str = Field(
        default="",
        description=(
            "The exact User-Agent string of the browser that produced "
            "session_cookie. Populated by `make refresh-cookie`. Shopee binds "
            "session cookies to a browser fingerprint (docs/research/data-surfaces.md "
            "§2.5); a mismatched UA on a real cookie is rejected with `error: "
            "90309999` even though the cookie itself is valid. Empty falls back "
            "to services.search.DEFAULT_USER_AGENT, which only works for "
            "anonymous/cold cookies, not a real logged-in session."
        ),
    )

    # --- Shopee affiliate portal (Surface B) ---
    affiliate_cookie: str = Field(
        default="",
        description=(
            "`; `-joined cookie string for affiliate.shopee.co.th. "
            "Populated by `make refresh-cookie`."
        ),
    )
    affiliate_id: str = Field(
        default="",
        description=(
            "Optional affiliate id; left empty until the empirical capture "
            "ticket confirms whether it's required."
        ),
    )

    # --- Generation ---
    generator: str = Field(
        default="stub",
        description=(
            "Output generator selector. 'stub' (default) → TemplateGenerator; "
            "'llm' → LLMGenerator (Google Gemini)."
        ),
    )

    # --- LLM (Google Gemini) ---
    gemini_api_key: str = Field(
        default="",
        description=(
            "Google AI Studio API key for Gemini. Get one free at "
            "https://aistudio.google.com/apikey. Required when "
            "SHOPEE_TH_GENERATOR=llm."
        ),
    )
    gemini_model: str = Field(
        default="gemini-2.5-flash",
        description="Gemini model id. gemini-2.5-flash is on the free tier.",
    )

    # --- Persistence ---
    db_url: str = Field(
        default="sqlite+aiosqlite:///./data/shopee_th.db",
        description="Async SQLAlchemy URL for the SQLite store.",
    )

    # --- Observability ---
    log_level: str = Field(default="INFO")


def get_settings() -> Settings:
    """Factory for dependency-injection / FastAPI Depends()."""
    return Settings()
