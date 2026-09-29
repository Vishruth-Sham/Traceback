"""Whisper.cpp transcription adapter.

`transcribe` shells out to the `whisper-cli` binary (Homebrew `whisper.cpp`)
against a caller-supplied audio path that is already persisted by the
backend; it never records audio itself and never treats model output as a
filesystem path.
"""

import shutil
import subprocess
from pathlib import Path

from processor.config import ProcessorSettings, get_settings
from processor.errors import ModelUnavailableError, NoSpeechError, TranscriptionError


def transcribe(audio_path: Path, *, settings: ProcessorSettings | None = None) -> str:
    """Transcribe an already-persisted audio file to text using local whisper.cpp.

    Raises `ModelUnavailableError` if the binary/model weights are missing and
    `TranscriptionError` for any other failure, so the caller can mark the
    saved capture failed instead of guessing at a result.
    """
    settings = settings or get_settings()
    audio_path = Path(audio_path)

    if not audio_path.is_file():
        raise TranscriptionError(f"audio file not found: {audio_path}")
    size = audio_path.stat().st_size
    if size == 0:
        raise TranscriptionError(f"audio file is empty: {audio_path}")
    if size > settings.whisper_max_audio_bytes:
        raise TranscriptionError(
            f"audio file too large ({size} bytes > {settings.whisper_max_audio_bytes} byte limit): {audio_path}"
        )

    binary = settings.whisper_binary
    resolved_binary = str(binary) if binary.is_file() else shutil.which(str(binary))
    if not resolved_binary:
        raise ModelUnavailableError(f"whisper.cpp binary not found: {binary}")
    if not settings.whisper_model_path.is_file():
        raise ModelUnavailableError(f"whisper.cpp model weights not found: {settings.whisper_model_path}")

    command = [
        resolved_binary,
        "-m",
        str(settings.whisper_model_path),
        "-f",
        str(audio_path),
        "-l",
        settings.whisper_language,
        "-nt",
        "-np",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=settings.whisper_timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise TranscriptionError(f"whisper.cpp timed out after {settings.whisper_timeout_s}s: {audio_path}") from exc
    except OSError as exc:
        raise ModelUnavailableError(f"failed to launch whisper.cpp: {exc}") from exc

    if result.returncode != 0:
        stderr_tail = result.stderr.strip()[-2000:]
        raise TranscriptionError(f"whisper.cpp exited {result.returncode}: {stderr_tail}")

    transcript = result.stdout.strip()
    if not transcript:
        raise NoSpeechError(f"whisper.cpp produced an empty transcript for {audio_path}")
    return transcript
