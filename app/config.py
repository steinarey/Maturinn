from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    db_schema: str = "maturinn"
    photos_dir: Path = Path("/data/photos")
    default_lang: str = "is"
    languages: tuple[str, ...] = ("is", "en")

    # LLM (import now; translation and cooking guide later). Provider-agnostic via LangChain.
    provider: Literal["anthropic", "openai", "gemini"] | None = None
    llm: str | None = None  # model name for that provider, e.g. claude-haiku-5-5, gpt-5.1, gemini-3.7-flash
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    gemini_api_key: str | None = None

    # Background worker that processes imports. Tests turn it off.
    worker_enabled: bool = True

    # Shopping list: a Home Assistant to-do list entity, via HA's REST API.
    home_assistant_url: str | None = None  # e.g. http://homeassistant.local:8123
    home_assistant_token: str | None = None  # long-lived access token
    home_assistant_todo: str | None = None  # default list, e.g. todo.shopping_list
    # When HA is reached by IP but its https certificate is for a name (e.g. a DuckDNS domain
    # that doesn't resolve locally): verify the certificate against this name instead.
    home_assistant_tls_hostname: str | None = None

    @field_validator("provider", "llm", "anthropic_api_key", "openai_api_key", "gemini_api_key",
                     "home_assistant_url", "home_assistant_token", "home_assistant_todo",
                     "home_assistant_tls_hostname", mode="before")
    @classmethod
    def _blank_is_none(cls, v):
        return None if isinstance(v, str) and not v.strip() else v

    def provider_key(self) -> str | None:
        return {
            "anthropic": self.anthropic_api_key,
            "openai": self.openai_api_key,
            "gemini": self.gemini_api_key,
        }.get(self.provider or "")

    @property
    def llm_configured(self) -> bool:
        return bool(self.provider and self.llm and self.provider_key())

    @property
    def shopping_configured(self) -> bool:
        return bool(self.home_assistant_url and self.home_assistant_token)

@lru_cache
def get_settings() -> Settings:
    return Settings()
