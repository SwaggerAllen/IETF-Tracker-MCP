"""Runtime settings sourced from environment variables.

Secrets and deployment-specific values come from the environment (App Platform /
GitHub Actions); non-secret application config lives in ``config.yaml``.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process settings read from the environment."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Defaults to a local SQLite file so the tool runs end-to-end offline for
    # development and the Milestone 1 spot-check. Production sets a Postgres URL.
    database_url: str = Field(default="sqlite:///./wgtracker.db", alias="DATABASE_URL")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    config_path: str = Field(default="config.yaml", alias="CONFIG_PATH")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    cost_ceiling_usd: float = Field(default=200.0, alias="COST_CEILING_USD")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
