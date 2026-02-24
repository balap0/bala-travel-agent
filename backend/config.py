# Configuration management — loads settings from environment variables
# Uses python-dotenv to load .env, then pydantic-settings for validation

import os
from pathlib import Path
from functools import lru_cache

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# Load .env file before pydantic-settings reads os.environ
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path, override=True)

# Fix SSL certificates on macOS (Amadeus SDK needs this)
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
except ImportError:
    pass


class Settings(BaseSettings):
    """App settings loaded from environment variables."""

    # Amadeus API
    amadeus_client_id: str = ""
    amadeus_client_secret: str = ""

    # SerpAPI
    serpapi_api_key: str = ""

    # Anthropic — read directly from os.environ to avoid __ mangling
    anthropic_api_key: str = ""

    # App auth
    app_password: str = "changeme"

    # Session
    session_secret: str = "dev-secret-change-in-production"

    # Environment
    environment: str = "development"

    # Claude model to use
    claude_model: str = "claude-sonnet-4-20250514"


@lru_cache()
def get_settings() -> Settings:
    """Cached settings singleton."""
    s = Settings()
    # Pydantic-settings treats __ as a nested model separator, which corrupts
    # API keys containing literal __ (like Anthropic keys). Read it directly.
    raw_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if raw_key and raw_key != s.anthropic_api_key:
        s = s.model_copy(update={"anthropic_api_key": raw_key})
    return s
