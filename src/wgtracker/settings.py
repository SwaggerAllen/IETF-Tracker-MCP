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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    # Defaults to a local SQLite file so the tool runs end-to-end offline for
    # development and the Milestone 1 spot-check. Production sets a Postgres URL.
    database_url: str = Field(default="sqlite:///./wgtracker.db", alias="DATABASE_URL")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    config_path: str = Field(default="config.yaml", alias="CONFIG_PATH")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    cost_ceiling_usd: float = Field(default=200.0, alias="COST_CEILING_USD")

    # Debug UI / MCP exposure (set on App Platform; empty => auth disabled for local dev).
    ui_basic_auth_user: str | None = Field(default=None, alias="UI_BASIC_AUTH_USER")
    ui_basic_auth_pass: str | None = Field(default=None, alias="UI_BASIC_AUTH_PASS")
    mcp_bearer_token: str | None = Field(default=None, alias="MCP_BEARER_TOKEN")

    # Lets the UI's re-trigger buttons dispatch the pipeline workflow.
    github_dispatch_token: str | None = Field(default=None, alias="GITHUB_DISPATCH_TOKEN")
    github_repo: str | None = Field(default=None, alias="GITHUB_REPO")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
