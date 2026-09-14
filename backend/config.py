from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRACEBACK_", env_file=".env", extra="ignore")

    database_url: str = Field(
        default="postgresql+psycopg://traceback:traceback@127.0.0.1:5432/traceback",
        validation_alias=AliasChoices("DATABASE_URL", "TRACEBACK_DATABASE_URL"),
    )
    api_token: str = Field(min_length=24)
    allowed_origins: str = "http://127.0.0.1:3000,http://localhost:3000"
    user_timezone: str = "Asia/Kolkata"
    max_page_size: int = Field(default=100, ge=1, le=250)
    asset_dir: Path = Path(".local/traceback/assets")
    max_upload_bytes: int = Field(default=100 * 1024 * 1024, ge=1)

    @property
    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
