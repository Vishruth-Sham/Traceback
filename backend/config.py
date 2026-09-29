from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
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

    # Voice commands (review-first). Env-only and read-only at runtime; restart the API to change.
    voice_commands_enabled: bool = False
    voice_max_seconds: int = Field(default=60, ge=5, le=300)
    voice_max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)
    voice_min_free_disk_bytes: int = Field(default=2 * 1024**3, ge=0)
    voice_auto_apply_intents: str = ""
    # `file --mime-type` labels WebM/Opus recordings "video/webm"; ffmpeg still has to decode the bytes.
    voice_accepted_mime_types: str = (
        "audio/webm,video/webm,audio/ogg,application/ogg,audio/mp4,video/mp4,audio/x-m4a,"
        "audio/mpeg,audio/wav,audio/x-wav,audio/x-hx-aac-adts"
    )
    voice_duplicate_window_s: int = Field(default=120, ge=0)
    voice_queue_aging_s: int = Field(default=300, ge=1)

    @field_validator("voice_auto_apply_intents")
    @classmethod
    def auto_apply_stays_off(cls, value: str) -> str:
        if value.strip():
            raise ValueError(
                "voice_auto_apply_intents must be empty: this release is review-first and implements no auto-apply"
            )
        return ""

    @property
    def voice_mime_types(self) -> list[str]:
        return [item.strip().lower() for item in self.voice_accepted_mime_types.split(",") if item.strip()]

    @property
    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
