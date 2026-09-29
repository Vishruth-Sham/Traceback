"""Runtime configuration for the local transcription/interpretation adapters.

Values are proposed defaults for a base M5 MacBook Air (16GB unified memory);
see docs/local-models.md for the measurements they are based on. Every field
is overridable through `TRACEBACK_PROCESSOR_*` environment variables or `.env`
so the coordinator's integration can tune them without editing this file.
"""

import shutil
from functools import lru_cache
import ipaddress
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_whisper_binary() -> Path:
    found = shutil.which("whisper-cli")
    return Path(found) if found else Path("whisper-cli")


class ProcessorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRACEBACK_PROCESSOR_", env_file=".env", extra="ignore")

    # Transcription (whisper.cpp)
    whisper_binary: Path = Field(default_factory=_default_whisper_binary)
    whisper_model_path: Path = Path.home() / ".cache" / "whisper-cpp" / "ggml-small.bin"
    whisper_language: str = "auto"
    whisper_timeout_s: float = Field(default=180.0, gt=0)
    whisper_max_audio_bytes: int = Field(default=100 * 1024 * 1024, ge=1)

    # Interpretation (loopback Ollama)
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.5:4b"
    ollama_timeout_s: float = Field(default=120.0, gt=0)
    ollama_num_ctx: int = Field(default=8192, ge=1024, le=32768)
    ollama_max_output_tokens: int = Field(default=700, ge=64, le=4096)
    ollama_max_input_chars: int = Field(default=12000, ge=500)
    ollama_temperature: float = Field(default=0.0, ge=0, le=2)
    ollama_retry_attempts: int = Field(default=2, ge=1, le=5)
    ollama_think: bool = False

    # Voice commands: normalization + strict slot extraction (local only; no cloud fallback)
    ffmpeg_binary: Path = Field(default_factory=lambda: Path(shutil.which("ffmpeg") or "ffmpeg"))
    ffmpeg_timeout_s: float = Field(default=30.0, gt=0)
    voice_max_audio_seconds: float = Field(default=65.0, gt=0, le=600)
    voice_min_audio_seconds: float = Field(default=0.7, ge=0)

    max_proposal_items: int = Field(default=10, ge=1, le=10)

    @field_validator("ollama_base_url")
    @classmethod
    def ollama_must_be_loopback(cls, value: str) -> str:
        parsed = urlparse(value)
        host = parsed.hostname
        try:
            loopback = host == "localhost" or (host is not None and ipaddress.ip_address(host).is_loopback)
        except ValueError:
            loopback = False
        if parsed.scheme != "http" or not loopback or parsed.username or parsed.password:
            raise ValueError("Ollama URL must be plain HTTP on a loopback address")
        return value


@lru_cache
def get_settings() -> ProcessorSettings:
    return ProcessorSettings()
