"""Runner tests.

Unit tests exercise `run_once` against a fake REST client (no network, no
models) covering: typed happy path, audio happy path (asset download +
transcribe), unsupported source types, and both branches of failure
reporting (lease still valid vs. already expired). A live integration test
runs the runner over real HTTP against the actual backend app (real
Postgres, real claim/lease/atomic-interpretation semantics) with the
transcribe/interpret adapters stubbed for determinism — the adapters
themselves are covered against real models in
tests/test_processor_transcription.py and tests/test_processor_interpretation.py.
"""
import socket
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

import processor.runner as runner_module
from processor.errors import ModelUnavailableError, TranscriptionError
from processor.runner import RestClient, RestError, RunnerConfig, run_once


class FakeRestClient:
    """Duck-types the subset of RestClient used by run_once."""

    def __init__(
        self,
        capture: dict,
        categories: list[dict] | None = None,
        projects: list[dict] | None = None,
        folders: list[dict] | None = None,
        asset_bytes: bytes = b"fake-audio",
    ):
        self.capture = capture
        self.categories = categories or []
        self.projects = projects or []
        self.folders = folders or []
        self.asset_bytes = asset_bytes
        self.claimed: list[dict] = []
        self.failed: list[dict] = []
        self.submitted: list[dict] = []
        self.downloaded: list[str] = []
        self.claim_conflict = False

    def list_categories(self):
        return self.categories

    def list_projects(self, limit=50):
        return self.projects

    def list_folders(self, limit=50):
        return self.folders

    def list_pending_captures(self, limit=1):
        return [] if self.capture is None else [self.capture]

    def get_capture(self, capture_id):
        return self.capture

    def claim_capture(self, capture_id, *, expected_generation, lease_seconds):
        if self.claim_conflict:
            raise RestError(409, {"code": "processing_conflict", "message": "already claimed"})
        self.claimed.append({"capture_id": capture_id, "expected_generation": expected_generation, "lease_seconds": lease_seconds})
        return {
            "capture_id": capture_id,
            "generation": expected_generation,
            "lease_token": str(uuid.uuid4()),
            "lease_expires_at": (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat(),
        }

    def fail_capture(self, capture_id, *, expected_generation, lease_token, error_code, error_message, transcript=None):
        record = {
            "capture_id": capture_id,
            "expected_generation": expected_generation,
            "lease_token": lease_token,
            "error_code": error_code,
            "error_message": error_message,
            "transcript": transcript,
        }
        self.failed.append(record)
        return record

    def submit_interpretation(self, capture_id, *, expected_version, expected_generation, lease_token, operations, transcript=None):
        record = {
            "capture_id": capture_id,
            "expected_version": expected_version,
            "expected_generation": expected_generation,
            "lease_token": lease_token,
            "operations": operations,
            "transcript": transcript,
        }
        self.submitted.append(record)
        return {"capture": {"id": capture_id}, "items": operations, "action_id": str(uuid.uuid4())}

    def download_asset_content(self, asset_id, destination: Path):
        self.downloaded.append(asset_id)
        destination.write_bytes(self.asset_bytes)


def _typed_capture(**overrides) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "source_type": "typed",
        "raw_text": "buy milk tomorrow",
        "asset_ids": [],
        "captured_at": "2026-09-14T09:00:00+05:30",
        "source_date": "2026-09-14",
        "source_timezone": "Asia/Kolkata",
        "version": 1,
        "processing": {"generation": 1, "state": "pending"},
    }
    base.update(overrides)
    return base


def _config() -> RunnerConfig:
    return RunnerConfig(api_base_url="http://127.0.0.1:0", api_token="unused-in-fake-client-tests")


def test_capture_processing_profile_is_forwarded_to_interpret_context(monkeypatch):
    """Regression guard: `run_once` must read `capture["metadata"]["processing_profile"]`
    and forward it into `interpret()`'s context unchanged. If this wiring silently
    breaks, task_quick_add captures fall back to the "general" profile and the
    backend's one-task enforcement (`backend/captures.py`) never gets a chance to
    matter, because `interpret()` itself stops requiring exactly one task."""
    seen_context: dict = {}

    def _capture_context(text, context, settings=None):
        seen_context.update(context)
        return {"items": [{"item_type": "task", "title": "x", "content_md": text, "category_id": None, "due_date": None, "due_time": None, "due_timezone": None}]}

    monkeypatch.setattr(runner_module, "interpret", _capture_context)
    capture = _typed_capture(metadata={"processing_profile": "task_quick_add"})
    fake = FakeRestClient(capture=capture)
    result = run_once(rest=fake, config=_config())
    assert result["status"] == "interpreted"
    assert seen_context["processing_profile"] == "task_quick_add"


def test_capture_without_metadata_defaults_to_general_profile(monkeypatch):
    seen_context: dict = {}

    def _capture_context(text, context, settings=None):
        seen_context.update(context)
        return {"items": [{"item_type": "note", "title": "x", "content_md": text, "category_id": None, "due_date": None, "due_time": None, "due_timezone": None}]}

    monkeypatch.setattr(runner_module, "interpret", _capture_context)
    fake = FakeRestClient(capture=_typed_capture())
    run_once(rest=fake, config=_config())
    assert seen_context["processing_profile"] == "general"


def test_runner_rejects_non_loopback_backend_url():
    with pytest.raises(ValidationError, match="loopback"):
        RunnerConfig(api_base_url="https://example.com", api_token="unused-test-token")


def test_no_pending_captures_returns_none():
    fake = FakeRestClient(capture=None)
    assert run_once(rest=fake, config=_config()) is None


def test_typed_capture_happy_path(monkeypatch):
    monkeypatch.setattr(runner_module, "interpret", lambda text, context, settings=None: {"items": [{"item_type": "note", "title": "x", "content_md": text, "category_id": None, "due_date": None, "due_time": None, "due_timezone": None}]})
    fake = FakeRestClient(capture=_typed_capture())
    result = run_once(rest=fake, config=_config())
    assert result["status"] == "interpreted"
    assert result["item_count"] == 1
    assert "result" not in result
    assert len(fake.claimed) == 1
    assert fake.downloaded == []
    assert fake.submitted[0]["transcript"] is None
    assert fake.submitted[0]["operations"][0]["item"]["content_md"] == "buy milk tomorrow"
    assert not fake.failed


def test_audio_capture_downloads_and_transcribes(monkeypatch):
    monkeypatch.setattr(runner_module, "transcribe", lambda path, settings=None: "transcribed text")
    monkeypatch.setattr(runner_module, "interpret", lambda text, context, settings=None: {"items": [{"item_type": "note", "title": "x", "content_md": text, "category_id": None, "due_date": None, "due_time": None, "due_timezone": None}]})
    capture = _typed_capture(source_type="audio", raw_text=None, asset_ids=[str(uuid.uuid4())])
    fake = FakeRestClient(capture=capture)
    result = run_once(rest=fake, config=_config())
    assert result["status"] == "interpreted"
    assert fake.downloaded == [capture["asset_ids"][0]]
    assert fake.submitted[0]["transcript"] == "transcribed text"
    assert fake.submitted[0]["operations"][0]["item"]["content_md"] == "transcribed text"


def test_proposed_project_id_is_resolved_to_a_placement_operation(monkeypatch):
    project_id = str(uuid.uuid4())
    monkeypatch.setattr(
        runner_module,
        "interpret",
        lambda text, context, settings=None: {
            "items": [
                {
                    "item_type": "task",
                    "title": "x",
                    "content_md": text,
                    "category_id": None,
                    "project_id": project_id,
                    "folder_id": None,
                    "due_date": None,
                    "due_time": None,
                    "due_timezone": None,
                }
            ]
        },
    )
    fake = FakeRestClient(capture=_typed_capture(), projects=[{"id": project_id, "title": "Apartment Move", "version": 3}])
    result = run_once(rest=fake, config=_config())
    assert result["status"] == "interpreted"
    operation = fake.submitted[0]["operations"][0]
    assert operation["project_id"] == project_id
    assert operation["project_expected_version"] == 3
    assert "folder_id" not in operation
    assert operation["item"]["category_id"] is None


def test_proposed_container_id_not_in_fetched_list_falls_back_to_unplaced(monkeypatch):
    # Simulates a container the model named that vanished/was archived between
    # context-building and this response; the id is not in our fetched list.
    stale_project_id = str(uuid.uuid4())
    monkeypatch.setattr(
        runner_module,
        "interpret",
        lambda text, context, settings=None: {
            "items": [
                {
                    "item_type": "task",
                    "title": "x",
                    "content_md": text,
                    "category_id": None,
                    "project_id": stale_project_id,
                    "folder_id": None,
                    "due_date": None,
                    "due_time": None,
                    "due_timezone": None,
                }
            ]
        },
    )
    fake = FakeRestClient(capture=_typed_capture(), projects=[])
    result = run_once(rest=fake, config=_config())
    assert result["status"] == "interpreted"
    operation = fake.submitted[0]["operations"][0]
    assert "project_id" not in operation
    assert "folder_id" not in operation
    assert operation["item"]["category_id"] is None


def test_audio_capture_without_assets_fails_cleanly():
    capture = _typed_capture(source_type="audio", raw_text=None, asset_ids=[])
    fake = FakeRestClient(capture=capture)
    result = run_once(rest=fake, config=_config())
    assert result["status"] == "failed"
    assert len(fake.failed) == 1
    assert fake.failed[0]["error_code"] == "ProcessorError"


def test_unsupported_source_type_fails_cleanly():
    fake = FakeRestClient(capture=_typed_capture(source_type="url"))
    result = run_once(rest=fake, config=_config())
    assert result["status"] == "failed"
    assert len(fake.failed) == 1


def test_transcription_error_reports_failure(monkeypatch):
    def _raise(path, settings=None):
        raise TranscriptionError("boom")

    monkeypatch.setattr(runner_module, "transcribe", _raise)
    capture = _typed_capture(source_type="audio", raw_text=None, asset_ids=[str(uuid.uuid4())])
    fake = FakeRestClient(capture=capture)
    result = run_once(rest=fake, config=_config())
    assert result["status"] == "failed"
    assert fake.failed[0]["error_code"] == "TranscriptionError"
    assert not fake.submitted


def test_expired_lease_skips_fail_report(monkeypatch):
    monkeypatch.setattr(runner_module, "interpret", lambda *a, **k: (_ for _ in ()).throw(ModelUnavailableError("down")))

    class ExpiredLeaseClient(FakeRestClient):
        def claim_capture(self, capture_id, *, expected_generation, lease_seconds):
            claim = super().claim_capture(capture_id, expected_generation=expected_generation, lease_seconds=lease_seconds)
            claim["lease_expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
            return claim

    fake = ExpiredLeaseClient(capture=_typed_capture())
    result = run_once(rest=fake, config=_config())
    assert result["status"] == "failed"
    assert not fake.failed  # lease already expired: no /fail call attempted


def test_claim_conflict_is_reported_without_raising():
    fake = FakeRestClient(capture=_typed_capture())
    fake.claim_conflict = True
    result = run_once(rest=fake, config=_config())
    assert result["status"] == "claim_conflict"


def test_backend_unavailable_during_claim_is_reported_without_raising():
    class UnavailableClaimClient(FakeRestClient):
        def claim_capture(self, capture_id, *, expected_generation, lease_seconds):
            raise ModelUnavailableError("could not reach backend API")

    fake = UnavailableClaimClient(capture=_typed_capture())
    result = run_once(rest=fake, config=_config())
    assert result == {"capture_id": fake.capture["id"], "status": "backend_unavailable"}
    assert not fake.failed  # no lease was ever acquired; nothing to report failed


# --- RestClient: a read timeout must become ModelUnavailableError, not escape raw ---


def test_request_read_timeout_becomes_model_unavailable_error(monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(runner_module.urllib.request, "urlopen", raise_timeout)
    rest = RestClient(_config())
    with pytest.raises(ModelUnavailableError, match="timed out"):
        rest.list_categories()


def test_download_asset_content_read_timeout_becomes_model_unavailable_error(monkeypatch, tmp_path):
    def raise_timeout(*args, **kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(runner_module.urllib.request, "urlopen", raise_timeout)
    rest = RestClient(_config())
    with pytest.raises(ModelUnavailableError, match="timed out"):
        rest.download_asset_content(str(uuid.uuid4()), tmp_path / "audio")


def test_read_timeout_during_processing_is_reported_as_failed(monkeypatch):
    """A TimeoutError raised mid-processing (after a successful claim) must still
    result in an explicit /fail report, not a stuck "processing" capture."""

    def raise_timeout(text, context, settings=None):
        raise TimeoutError("timed out")

    def _interpret_via_rest_client(*a, **k):
        # Exercise the real RestClient's timeout mapping, not just the fake.
        raise ModelUnavailableError("timed out waiting for backend API")

    monkeypatch.setattr(runner_module, "interpret", _interpret_via_rest_client)
    fake = FakeRestClient(capture=_typed_capture())
    result = run_once(rest=fake, config=_config())
    assert result["status"] == "failed"
    assert fake.failed[0]["error_code"] == "ModelUnavailableError"


# --- Live integration: real backend over real HTTP, adapters stubbed for determinism ---


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


def test_runner_against_live_backend(client, live_server, monkeypatch):
    monkeypatch.setattr(
        runner_module,
        "interpret",
        lambda text, context, settings=None: {
            "items": [
                {"item_type": "note", "title": "Runner integration note", "content_md": text, "category_id": None, "due_date": None, "due_time": None, "due_timezone": None}
            ]
        },
    )
    created = client.post("/api/v1/captures", json={"source_type": "typed", "raw_text": "runner integration capture text"}).json()

    config = RunnerConfig(api_base_url=live_server, api_token="traceback-integration-test-token-only")
    rest = RestClient(config)
    result = run_once(rest=rest, config=config)

    assert result["status"] == "interpreted"
    assert result["capture_id"] == created["id"]

    refreshed = client.get(f"/api/v1/captures/{created['id']}").json()
    assert refreshed["processing"]["state"] == "resolved"
    assert len(refreshed["resulting_item_ids"]) == 1

    item = client.get(f"/api/v1/items/{refreshed['resulting_item_ids'][0]}").json()
    assert item["title"] == "Runner integration note"
    assert item["content_md"] == "runner integration capture text"
