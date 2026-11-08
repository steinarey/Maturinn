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

    # Shopping list: Microsoft To Do through an Azure app registration (Microsoft Graph).
    microsoft_client_id: str | None = None
    microsoft_client_secret: str | None = None
    microsoft_authority: str = "https://login.microsoftonline.com/common"
    microsoft_scopes: str = "Tasks.ReadWrite User.Read"
    # Must match a redirect URI registered on the app. Empty = derived from the request URL.
    microsoft_redirect_uri: str | None = None

    @field_validator("provider", "llm", "anthropic_api_key", "openai_api_key", "gemini_api_key",
                     "microsoft_client_id", "microsoft_client_secret", "microsoft_redirect_uri", mode="before")
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
        return bool(self.microsoft_client_id and self.microsoft_client_secret)

    @property
    def microsoft_scope_list(self) -> list[str]:
        # MSAL adds these itself and refuses them in the list.
        reserved = {"openid", "profile", "offline_access"}
        return [x for x in self.microsoft_scopes.replace(",", " ").split() if x.lower() not in reserved]

@lru_cache
def get_settings() -> Settings:
    return Settings()
