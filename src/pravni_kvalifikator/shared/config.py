"""Global configuration — Pydantic Settings with .env file."""

import logging
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

EMBEDDING_DIMENSIONS = 1536


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Azure OpenAI
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_chat_deployment: str = "gpt-5.2"
    azure_openai_embedding_deployment: str = "text-embedding-3-large"

    # Database
    laws_db_path: Path = Field(default=Path("./data/laws.db"))
    sessions_db_path: Path = Field(default=Path("./data/sessions.db"))

    # MCP Server
    mcp_server_host: str = "0.0.0.0"
    mcp_server_port: int = 8001

    # Web App
    web_host: str = "0.0.0.0"
    web_port: int = 8000
    mcp_server_url: str = "http://localhost:8001"

    # Scraper
    scraper_delay: float = 1.5
    scraper_user_agent: str = "LegalQualifier/1.0"

    # Auth
    auth_hmac_key: str = ""  # Prázdný = auth vypnutá (dev režim)

    # Misc
    log_level: str = "INFO"
    session_expiry_days: int = 30

    @field_validator("laws_db_path", "sessions_db_path", mode="before")
    @classmethod
    def convert_to_path(cls, v: str | Path) -> Path:
        return Path(v) if isinstance(v, str) else v


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return singleton Settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def setup_logging(level: str = "INFO") -> None:
    """Configure logging with the given level."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
