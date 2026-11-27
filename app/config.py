from functools import lru_cache
from typing import Any, Literal

from pydantic import SecretStr
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
    generator_timeout_seconds: Any = DEFAULT_GENERATOR_TIMEOUT_SECONDS
    generator_max_input_chars: Any = DEFAULT_GENERATOR_MAX_INPUT_CHARS
    polly_enabled: bool = False
    polly_region: str = ""
    polly_voice_id: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
