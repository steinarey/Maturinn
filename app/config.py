from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    db_schema: str = "maturinn"
    photos_dir: Path = Path("/data/photos")
    default_lang: str = "is"
    languages: tuple[str, ...] = ("is", "en")

    # Feature flags for later phases. Off until their integrations exist.
    llm_enabled: bool = False
    anthropic_api_key: str | None = None
    llm_model: str | None = None
    shopping_enabled: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
