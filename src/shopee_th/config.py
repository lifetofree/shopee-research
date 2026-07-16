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
            "'llm' → LLMGenerator (not implemented this iteration)."
        ),
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
