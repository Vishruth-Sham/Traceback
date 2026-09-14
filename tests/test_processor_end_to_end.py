"""End-to-end capture-processing tests against real PostgreSQL/HTTP.

Three groups, in order:

1. Deterministic REST-level tests (the `client` fixture only — real Postgres,
   in-process ASGI, no sockets needed) covering claim/lease/generation
   conflict safety and the specific guarantee that a stale automated write
   (an in-flight processor claim, or an append using a version read before
   a concurrent manual edit) cannot silently overwrite a manual edit.
2. Deterministic runner-through-real-HTTP tests (`live_server` + the real
   `processor.runner.RestClient`/`run_once`, `transcribe`/`interpret`
   stubbed) covering the audio pipeline's wiring (asset download → stub
   transcript → stub interpretation → atomic REST write) and failure
   preservation/retry recovery — deterministic because the fixture data and
   stub outputs are fixed, not because a real model was involved.
3. Real-model tests, skipped with a precise reason when whisper.cpp/Ollama
   aren't installed on this machine, running the full unstubbed pipeline
   for a typed and (via macOS `say`/`afconvert` synthetic speech, matching
   scripts/model_smoke.py) an audio capture. These do not assert exact
   transcript/interpretation wording — real model output quality is
   explicitly out of scope here (see docs/local-models.md) — only that the
   real pipeline reaches a schema-valid, persisted, resolved result.
"""
import json
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

import processor.runner as runner_module
from processor.config import get_settings as get_processor_settings
from processor.errors import TranscriptionError
from processor.runner import RestClient, RunnerConfig, run_once

WHISPER_AVAILABLE = bool(shutil.which("whisper-cli")) and get_processor_settings().whisper_model_path.is_file()
SYNTH_AVAILABLE = bool(shutil.which("say")) and bool(shutil.which("afconvert"))


def _ollama_model_available() -> bool:
    import urllib.request

    settings = get_processor_settings()
    try:
        with urllib.request.urlopen(settings.ollama_base_url.rstrip("/") + "/api/tags", timeout=3) as response:
            tags = json.loads(response.read())
    except Exception:
        return False
    return any(m.get("name") == settings.ollama_model for m in tags.get("models", []))


requires_whisper_and_synth = pytest.mark.skipif(
    not (WHISPER_AVAILABLE and SYNTH_AVAILABLE),
    reason="whisper-cli/model weights or macOS say/afconvert not available",
)
requires_ollama = pytest.mark.skipif(
    not _ollama_model_available(), reason=f"Ollama loopback service or model {get_processor_settings().ollama_model} not available"
)


# =====================================================================================
# Group 1: deterministic REST-level conflict/staleness safety (client fixture only)
# =====================================================================================


def _create_typed_capture(client, text="Buy milk tomorrow"):
    response = client.post("/api/v1/captures", json={"source_type": "typed", "raw_text": text})
    assert response.status_code == 201, response.text
    return response.json()


def _claim(client, capture, lease_seconds=30):
    response = client.post(
        f"/api/v1/captures/{capture['id']}/claim",
        json={"expected_generation": capture["processing"]["generation"], "lease_seconds": lease_seconds},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_concurrent_claim_is_rejected_while_lease_active(client):
    capture = _create_typed_capture(client)
    first = _claim(client, capture)
    assert first["generation"] == 1

    second = client.post(
        f"/api/v1/captures/{capture['id']}/claim",
        json={"expected_generation": 1, "lease_seconds": 30},
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "processing_conflict"


def test_stale_processor_interpretation_cannot_overwrite_manual_resolution(client):
    """A processor holding a lease from before a manual resolution must be
    fenced out, not allowed to create a second, conflicting result."""
    capture = _create_typed_capture(client, text="Read the distributed systems chapter")
    claim = _claim(client, capture)
    stale_generation = claim["generation"]
    stale_lease_token = claim["lease_token"]

    # The user resolves it manually before the processor ever submits.
    manual = client.post(
        f"/api/v1/captures/{capture['id']}/interpretations",
        json={
            "expected_version": capture["version"],
            "expected_generation": stale_generation,
            "mode": "manual",
            "items": [{"kind": "create", "item": {"item_type": "note", "title": "Manual note", "content_md": "user-authored"}}],
        },
    )
    assert manual.status_code == 200, manual.text
    manual_body = manual.json()
    manual_item_id = manual_body["items"][0]["id"]
    assert manual_body["capture"]["processing"]["state"] == "resolved"
    # Manual resolution advances the generation specifically to fence stale automated work.
    assert manual_body["capture"]["processing"]["generation"] == stale_generation + 1

    # The processor, unaware, now tries to submit using its stale claim.
    stale_submit = client.post(
        f"/api/v1/captures/{capture['id']}/interpretations",
        json={
            "expected_version": manual_body["capture"]["version"],
            "expected_generation": stale_generation,
            "mode": "processor",
            "lease_token": stale_lease_token,
            "items": [{"kind": "create", "item": {"item_type": "note", "title": "Stale processor note", "content_md": "should never land"}}],
        },
    )
    assert stale_submit.status_code == 409
    assert stale_submit.json()["error"]["code"] in ("processing_conflict", "processing_generation_conflict")

    # Only the manual item exists; the capture still resolves to exactly one result.
    refreshed = client.get(f"/api/v1/captures/{capture['id']}").json()
    assert refreshed["resulting_item_ids"] == [manual_item_id]
    manual_item = client.get(f"/api/v1/items/{manual_item_id}").json()
    assert manual_item["content_md"] == "user-authored"


def test_stale_automated_append_cannot_overwrite_a_concurrent_manual_edit(client):
    """Same guarantee at the item level: an interpretation append using a
    version read before a concurrent manual edit must conflict, not
    silently clobber the user's edit."""
    note = client.post("/api/v1/items", json={"item_type": "note", "title": "Shared note", "content_md": "Original"}).json()
    capture = _create_typed_capture(client, text="Add this to the shared note")
    claim = _claim(client, capture)

    # The user edits the note manually while the (hypothetical) processor
    # still holds the version it read before claiming.
    manual_edit = client.patch(f"/api/v1/items/{note['id']}", json={"expected_version": note["version"], "content_md": "Original\n\nUser's own addition"})
    assert manual_edit.status_code == 200
    assert manual_edit.json()["version"] == note["version"] + 1

    stale_append = client.post(
        f"/api/v1/captures/{capture['id']}/interpretations",
        json={
            "expected_version": capture["version"],
            "expected_generation": claim["generation"],
            "mode": "processor",
            "lease_token": claim["lease_token"],
            "items": [{"kind": "append", "item_id": note["id"], "expected_version": note["version"], "content_md": "stale automated append"}],
        },
    )
    assert stale_append.status_code == 409
    assert stale_append.json()["error"]["code"] == "version_conflict"

    unchanged = client.get(f"/api/v1/items/{note['id']}").json()
    assert unchanged["content_md"] == "Original\n\nUser's own addition"
    assert "stale automated append" not in unchanged["content_md"]


def test_retry_after_failure_fences_the_old_lease_and_generation(client):
    capture = _create_typed_capture(client)
    claim = _claim(client, capture)

    failed = client.post(
        f"/api/v1/captures/{capture['id']}/fail",
        json={"expected_generation": claim["generation"], "lease_token": claim["lease_token"], "error_code": "TranscriptionError", "error_message": "synthetic failure for test"},
    )
    assert failed.status_code == 200
    assert failed.json()["processing"]["state"] == "failed"

    # The old lease/generation is now dead; retry is required before reclaiming.
    stale_reclaim = client.post(
        f"/api/v1/captures/{capture['id']}/claim",
        json={"expected_generation": claim["generation"], "lease_seconds": 30},
    )
    assert stale_reclaim.status_code == 409

    retried = client.post(
        f"/api/v1/captures/{capture['id']}/retry",
        json={"expected_version": failed.json()["version"], "expected_generation": claim["generation"]},
    )
    assert retried.status_code == 200
    new_generation = retried.json()["processing"]["generation"]
    assert new_generation == claim["generation"] + 1
    assert retried.json()["processing"]["state"] == "pending"

    reclaimed = client.post(
        f"/api/v1/captures/{capture['id']}/claim",
        json={"expected_generation": new_generation, "lease_seconds": 30},
    )
    assert reclaimed.status_code == 200


# =====================================================================================
# Group 2: deterministic runner-through-real-HTTP (transcribe/interpret stubbed)
# =====================================================================================


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def live_server(client):
    uvicorn = pytest.importorskip("uvicorn")
    from backend.main import app

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not getattr(server, "started", False) and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "backend did not start within 10s"
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _tiny_deterministic_wav(path: Path) -> None:
    """A short, fully deterministic silent WAV — no `say`/microphone involved."""
    import wave

    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\x00\x00" * 1600)  # 0.1s of silence


def _upload_asset(rest_base_url: str, token: str, wav_path: Path) -> str:
    import urllib.request

    with open(wav_path, "rb") as fh:
        payload = fh.read()
    request = urllib.request.Request(
        url=f"{rest_base_url}/api/v1/assets?filename=capture-audio.wav",
        data=payload,
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "audio/wav"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())["id"]


def test_audio_capture_through_runner_over_real_http_deterministic(client, live_server, monkeypatch, tmp_path):
    monkeypatch.setattr(runner_module, "transcribe", lambda path, settings=None: "deterministic stub transcript")
    monkeypatch.setattr(
        runner_module,
        "interpret",
        lambda text, context, settings=None: {
            "items": [{"item_type": "note", "title": "Audio pipeline note", "content_md": text, "category_id": None, "due_date": None, "due_time": None, "due_timezone": None}]
        },
    )

    token = "traceback-integration-test-token-only"
    wav_path = tmp_path / "fixture.wav"
    _tiny_deterministic_wav(wav_path)
    asset_id = _upload_asset(live_server, token, wav_path)

    created = client.post("/api/v1/captures", json={"source_type": "audio", "asset_ids": [asset_id]}).json()

    config = RunnerConfig(api_base_url=live_server, api_token=token)
    rest = RestClient(config)
    result = run_once(rest=rest, config=config)

    assert result["status"] == "interpreted"
    refreshed = client.get(f"/api/v1/captures/{created['id']}").json()
    assert refreshed["processing"]["state"] == "resolved"
    assert refreshed["processing"]["transcript"] == "deterministic stub transcript"
    assert refreshed["asset_ids"] == [asset_id]  # original asset link preserved, not consumed

    item = client.get(f"/api/v1/items/{refreshed['resulting_item_ids'][0]}").json()
    assert item["content_md"] == "deterministic stub transcript"


def test_transcription_failure_is_preserved_then_recovers_on_retry(client, live_server, monkeypatch, tmp_path):
    token = "traceback-integration-test-token-only"
    wav_path = tmp_path / "fixture.wav"
    _tiny_deterministic_wav(wav_path)
    asset_id = _upload_asset(live_server, token, wav_path)
    created = client.post("/api/v1/captures", json={"source_type": "audio", "asset_ids": [asset_id]}).json()

    def _always_fails(path, settings=None):
        raise TranscriptionError("synthetic deterministic failure")

    monkeypatch.setattr(runner_module, "transcribe", _always_fails)
    config = RunnerConfig(api_base_url=live_server, api_token=token)
    rest = RestClient(config)

    first = run_once(rest=rest, config=config)
    assert first["status"] == "failed"
    assert first["error_code"] == "TranscriptionError"

    failed_capture = client.get(f"/api/v1/captures/{created['id']}").json()
    assert failed_capture["processing"]["state"] == "failed"
    assert failed_capture["processing"]["error_code"] == "TranscriptionError"
    # The original asset survives a processing failure untouched.
    content = client.get(f"/api/v1/assets/{asset_id}/content")
    assert content.status_code == 200 and len(content.content) > 0

    retried = client.post(
        f"/api/v1/captures/{created['id']}/retry",
        json={"expected_version": failed_capture["version"], "expected_generation": failed_capture["processing"]["generation"]},
    )
    assert retried.status_code == 200

    monkeypatch.setattr(runner_module, "transcribe", lambda path, settings=None: "recovered transcript")
    monkeypatch.setattr(
        runner_module,
        "interpret",
        lambda text, context, settings=None: {
            "items": [{"item_type": "note", "title": "Recovered", "content_md": text, "category_id": None, "due_date": None, "due_time": None, "due_timezone": None}]
        },
    )
    second = run_once(rest=rest, config=config)
    assert second["status"] == "interpreted"
    resolved_capture = client.get(f"/api/v1/captures/{created['id']}").json()
    assert resolved_capture["processing"]["state"] == "resolved"
    assert resolved_capture["processing"]["transcript"] == "recovered transcript"


# =====================================================================================
# Group 3: real, unstubbed models — gated, no quality claims
# =====================================================================================


@requires_ollama
def test_typed_capture_full_pipeline_with_real_ollama(client, live_server):
    token = "traceback-integration-test-token-only"
    created = client.post(
        "/api/v1/captures", json={"source_type": "typed", "raw_text": "Note to self: read the intro chapter this weekend."}
    ).json()

    config = RunnerConfig(api_base_url=live_server, api_token=token)
    rest = RestClient(config)
    result = run_once(rest=rest, config=config)

    assert result["status"] == "interpreted"
    refreshed = client.get(f"/api/v1/captures/{created['id']}").json()
    assert refreshed["processing"]["state"] == "resolved"
    assert len(refreshed["resulting_item_ids"]) >= 1
    item = client.get(f"/api/v1/items/{refreshed['resulting_item_ids'][0]}").json()
    assert item["item_type"] in ("note", "task", "project")
    # No quality claim beyond schema validity: real-model extraction accuracy
    # is explicitly out of scope (docs/local-models.md).


@requires_whisper_and_synth
@requires_ollama
def test_audio_capture_full_pipeline_with_real_whisper_and_ollama(client, live_server, tmp_path):
    token = "traceback-integration-test-token-only"
    aiff_path = tmp_path / "fixture.aiff"
    wav_path = tmp_path / "fixture.wav"
    subprocess.run(["say", "-o", str(aiff_path), "Buy milk tomorrow for Traceback"], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(aiff_path), str(wav_path)], check=True)

    asset_id = _upload_asset(live_server, token, wav_path)
    created = client.post("/api/v1/captures", json={"source_type": "audio", "asset_ids": [asset_id]}).json()

    config = RunnerConfig(api_base_url=live_server, api_token=token)
    rest = RestClient(config)
    result = run_once(rest=rest, config=config)

    assert result["status"] == "interpreted"
    refreshed = client.get(f"/api/v1/captures/{created['id']}").json()
    assert refreshed["processing"]["state"] == "resolved"
    assert refreshed["processing"]["transcript"]  # non-empty real transcript
    assert len(refreshed["resulting_item_ids"]) >= 1
    item = client.get(f"/api/v1/items/{refreshed['resulting_item_ids'][0]}").json()
    assert item["item_type"] in ("note", "task", "project")
