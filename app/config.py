from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

GeneratorProvider = Literal["mock", "openai_compatible"]
DEFAULT_GENERATOR_BASE_URL = "https://api.openai.com/v1"
DEFAULT_GENERATOR_TIMEOUT_SECONDS = 30.0
MAX_GENERATOR_TIMEOUT_SECONDS = 120.0
DEFAULT_GENERATOR_MAX_INPUT_CHARS = 8000
MIN_GENERATOR_INPUT_CHARS = 10
MAX_GENERATOR_INPUT_CHARS = 20000


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = (
        "postgresql+psycopg://techcards:local-development-only@localhost:5435/techcards"
    )
    generator_provider: GeneratorProvider = "mock"
    generator_api_key: SecretStr | None = None
    generator_model: str | None = None
    generator_base_url: str = DEFAULT_GENERATOR_BASE_URL
    generator_timeout_seconds: float = Field(
        default=DEFAULT_GENERATOR_TIMEOUT_SECONDS,
        gt=0.0,
        le=MAX_GENERATOR_TIMEOUT_SECONDS,
        allow_inf_nan=False,
    )
    generator_max_input_chars: int = Field(
        default=DEFAULT_GENERATOR_MAX_INPUT_CHARS,
        ge=MIN_GENERATOR_INPUT_CHARS,
        le=MAX_GENERATOR_INPUT_CHARS,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
