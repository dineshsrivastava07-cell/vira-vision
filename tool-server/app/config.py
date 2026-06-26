"""Central configuration — all values from environment, nothing sensitive in code."""
from __future__ import annotations
import os
from functools import lru_cache

def _split(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]

class Settings:
    CLAUDE_API_KEY: str = os.getenv("CLAUDE_API_KEY", "")
    CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
    CH_URL: str = os.getenv("CH_URL", "http://localhost:8123")
    CH_USER: str = os.getenv("CH_USER", "default")
    CH_KEY: str = os.getenv("CH_KEY", "")
    CH_DATABASE: str = os.getenv("CH_DATABASE", "default")
    CH_MAX_ROWS: int = int(os.getenv("CH_MAX_ROWS", "5000"))
    CH_TIMEOUT_S: int = int(os.getenv("CH_TIMEOUT_S", "60"))
    EXCLUDED_DIVISIONS: list[str] = _split(
        os.getenv("EXCLUDED_DIVISIONS", "Others,Fixed Assets,Repair and Maintenance,Marketing N Advertisement")
    )
    EXCLUDED_STORE_TYPES: list[str] = _split(os.getenv("EXCLUDED_STORE_TYPES", ""))
    TS_HOST: str = os.getenv("TS_HOST", "")
    TS_SESSION_COOKIE: str = os.getenv("TS_SESSION_COOKIE", "")
    TS_CSRF_TOKEN: str = os.getenv("TS_CSRF_TOKEN", "")
    TS_BEARER_TOKEN: str = os.getenv("TS_BEARER_TOKEN", "")
    TS_USERNAME: str = os.getenv("TS_USERNAME", "")
    TS_PASSWORD: str = os.getenv("TS_PASSWORD", "")
    TS_SECRET_KEY: str = os.getenv("TS_SECRET_KEY", "")
    TS_TOKEN_VALIDITY_S: int = int(os.getenv("TS_TOKEN_VALIDITY_S", "86400"))
    TS_DEFAULT_WORKSHEET: str = os.getenv("TS_DEFAULT_WORKSHEET", "")
    WORKFLOW_WEBHOOK_BASE: str = os.getenv("WORKFLOW_WEBHOOK_BASE", "")
    ALLOWED_ORIGINS: list[str] = _split(os.getenv("ALLOWED_ORIGINS", "*"))

@lru_cache
def get_settings() -> Settings:
    return Settings()
