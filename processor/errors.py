"""Exceptions raised by processor adapters so the caller can mark a capture failed."""


class ProcessorError(RuntimeError):
    """Base class for processor adapter failures.

    A subclass may set `error_code`; otherwise the class name is reported to the backend.
    """

    error_code: str | None = None


class ModelUnavailableError(ProcessorError):
    """Raised when a required local binary/model/service cannot be reached."""


class TranscriptionError(ProcessorError):
    """Raised when whisper.cpp fails to produce a transcript."""


class InterpretationError(ProcessorError):
    """Raised when Ollama fails to produce a valid proposal envelope."""


class NoSpeechError(TranscriptionError):
    """Raised when the recording contains no usable speech (silence, too short, or blank markers)."""

    error_code = "no_speech"


class AudioNormalizationError(TranscriptionError):
    """Raised when ffmpeg cannot decode the saved recording into 16 kHz mono WAV."""

    error_code = "unsupported_audio"


class AudioTooLongError(TranscriptionError):
    error_code = "audio_too_long"


class LegacyAudioRequiresReview(ProcessorError):
    """General (legacy) audio is transcribed and checkpointed but never auto-interpreted."""

    error_code = "legacy_audio_requires_review"
