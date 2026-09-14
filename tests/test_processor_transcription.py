"""Transcription adapter tests against a synthetic (say/afconvert) audio fixture.

Skips with a precise reason, rather than failing, when whisper.cpp or the
macOS `say`/`afconvert` synthesis tools are unavailable on this runtime.
"""
import shutil
import subprocess

import pytest

from processor.config import get_settings
from processor.errors import ModelUnavailableError, TranscriptionError
from processor.transcription import transcribe

WHISPER_AVAILABLE = bool(shutil.which("whisper-cli")) and get_settings().whisper_model_path.is_file()
SYNTH_AVAILABLE = bool(shutil.which("say")) and bool(shutil.which("afconvert"))

requires_whisper = pytest.mark.skipif(
    not WHISPER_AVAILABLE,
    reason=f"whisper-cli binary or model weights ({get_settings().whisper_model_path}) not installed",
)
requires_synth = pytest.mark.skipif(
    not SYNTH_AVAILABLE, reason="macOS `say`/`afconvert` not available to synthesize a fixture"
)


@pytest.fixture(scope="module")
def synthetic_wav(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("processor-audio-fixture")
    aiff_path = tmp_dir / "fixture.aiff"
    wav_path = tmp_dir / "fixture.wav"
    subprocess.run(["say", "-o", str(aiff_path), "Buy milk tomorrow for Traceback"], check=True)
    subprocess.run(
        ["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(aiff_path), str(wav_path)], check=True
    )
    return wav_path


@requires_synth
@requires_whisper
def test_transcribe_synthetic_speech(synthetic_wav):
    text = transcribe(synthetic_wav)
    assert isinstance(text, str) and text.strip()
    # Loose containment check: whisper output wording/punctuation can vary slightly.
    assert "milk" in text.lower()


def test_transcribe_missing_file_raises():
    with pytest.raises(TranscriptionError):
        transcribe("/nonexistent/path/does-not-exist.wav")


def test_transcribe_empty_file_raises(tmp_path):
    empty = tmp_path / "empty.wav"
    empty.write_bytes(b"")
    with pytest.raises(TranscriptionError):
        transcribe(empty)


def test_transcribe_missing_binary_raises_model_unavailable(tmp_path, monkeypatch):
    settings = get_settings().model_copy(update={"whisper_binary": tmp_path / "no-such-binary"})
    audio = tmp_path / "fixture.wav"
    audio.write_bytes(b"not empty")
    with pytest.raises(ModelUnavailableError):
        transcribe(audio, settings=settings)
