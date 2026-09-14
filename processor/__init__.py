"""Local capture processing adapters: whisper.cpp transcription and Ollama interpretation.

No database writes and no network calls beyond loopback Ollama happen here;
see docs/local-models.md for the integration contract and runtime evidence.
"""

from processor.errors import InterpretationError, ModelUnavailableError, TranscriptionError
from processor.interpretation import interpret
from processor.transcription import transcribe

__all__ = [
    "InterpretationError",
    "ModelUnavailableError",
    "TranscriptionError",
    "interpret",
    "transcribe",
]

# processor.runner is intentionally not imported here to keep importing the
# transcribe/interpret adapters free of REST-client concerns. Import it
# explicitly: `from processor import runner`.
