from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = (
        "postgresql+psycopg://techcards:local-development-only@localhost:5435/techcards"
    )
    generator_provider: Literal["mock"] = "mock"
    polly_enabled: bool = False
    polly_region: str = ""
    polly_voice_id: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
