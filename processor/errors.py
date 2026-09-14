"""Exceptions raised by processor adapters so the caller can mark a capture failed."""


class ProcessorError(RuntimeError):
    """Base class for processor adapter failures."""


class ModelUnavailableError(ProcessorError):
    """Raised when a required local binary/model/service cannot be reached."""


class TranscriptionError(ProcessorError):
    """Raised when whisper.cpp fails to produce a transcript."""


class InterpretationError(ProcessorError):
    """Raised when Ollama fails to produce a valid proposal envelope."""
