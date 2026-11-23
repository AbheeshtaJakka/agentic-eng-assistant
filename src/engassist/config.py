"""Typed configuration from environment / .env (12-factor). Secrets come from the environment
in every deployment; `.env` is only a local-development convenience and is git-ignored."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str | None = None

    # Leave blank to use the Agents SDK's default model; set to any model your account can use.
    coding_model: str | None = None
    max_turns: int = 25  # one turn = one model call (plus the tool calls it makes)
    task_timeout_s: float = 300.0

    # The API only accepts repo NAMES under this directory (never client-supplied paths).
    repos_root: Path = Path("./repos")
    audit_log_path: Path = Path("./var/audit.jsonl")

    tracing_disabled: bool = False
    log_level: str = "INFO"

    @field_validator("openai_api_key", "coding_model", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        return v or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
