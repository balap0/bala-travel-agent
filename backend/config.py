# Configuration management — loads settings from environment variables

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """App settings loaded from environment variables or .env file."""

    # Amadeus API
    amadeus_client_id: str = ""
    amadeus_client_secret: str = ""

    # SerpAPI
    serpapi_api_key: str = ""

    # Anthropic
    anthropic_api_key: str = ""

    # App auth
    app_password: str = "changeme"

    # Session
    session_secret: str = "dev-secret-change-in-production"

    # Environment
    environment: str = "development"

    # Claude model to use
    claude_model: str = "claude-sonnet-4-20250514"

    model_config = {
        "env_file": "../.env",
        "env_file_encoding": "utf-8",
    }


@lru_cache()
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
