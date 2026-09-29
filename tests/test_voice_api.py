"""PostgreSQL-backed voice-command contract: ingest, fencing, proposals, accept, audit, disabled mode, queue."""
import concurrent.futures
import errno
import hashlib
import io
import os
import uuid
import wave
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from tests.conftest import drain_claimable_captures
from tests.test_processor_end_to_end import live_server  # noqa: F401  (real uvicorn for concurrent ingest)

IST = ZoneInfo("Asia/Kolkata")
TOKEN = "traceback-integration-test-token-only"
API = "/api/v1"


# backend modules are imported lazily: the session `client` fixture must set the throwaway-database
# environment before `backend.main` (and its module-level engine) is first imported.
def current_settings():
    from backend.config import get_settings

    return get_settings()


def settings_override(**update):
    from backend.config import get_settings
    from backend.main import app

    base = get_settings()
    app.dependency_overrides[get_settings] = lambda: base.model_copy(update=update)


def clear_override():
    from backend.config import get_settings
    from backend.main import app

    app.dependency_overrides.pop(get_settings, None)


@pytest.fixture
def voice(client):
    settings_override(voice_commands_enabled=True, voice_min_free_disk_bytes=0)
    yield
    clear_override()


@pytest.fixture
def voice_disabled(client):
    settings_override(voice_commands_enabled=False)
    yield
    clear_override()


def now_ist() -> datetime:
    return datetime.now(IST).replace(microsecond=0)


def wav_bytes(seed: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes((uuid.uuid4().hex if seed is None else seed).encode() * (1000 if seed is None else 200))
    return buffer.getvalue()


def ingest(client, data: bytes | None = None, key: str | None = None, *, captured=None, **overrides):
    data = wav_bytes() if data is None else data
    params = {
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "captured_at": (captured or now_ist()).isoformat(),
        "source_timezone": "Asia/Kolkata",
        "entry_point": "global",
        "filename": "voice.wav",
        **overrides,
    }
    headers = {"Content-Type": "audio/wav"}
    if key is not False:
        headers["Idempotency-Key"] = key or uuid.uuid4().hex
    return client.post(f"{API}/voice-captures", params=params, content=data, headers=headers)


def typed_voice(client, text, *, captured=None, **metadata):
    response = client.post(
        f"{API}/captures",
        json={
            "source_type": "typed",
            "raw_text": text,
            "captured_at": (captured or now_ist()).isoformat(),
            "source_timezone": "Asia/Kolkata",
            "timestamp_origin": "client_supplied",
            "metadata": {"processing_profile": "voice_command", "entry_point": "global", **metadata},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def slots(**overrides):
    base = dict(intent="create_note", title=None, content=None, destination_phrase=None, target_phrase=None, date_phrase=None, time_phrase=None, flags=[], reason="test")
    base.update(overrides)
    return base


def claim(client, capture):
    response = client.post(f"{API}/captures/{capture['id']}/claim", json={"expected_generation": capture["processing"]["generation"]})
    assert response.status_code == 200, response.text
    return response.json()


def propose(client, capture, slot_values, lease=None, **extra):
    lease = lease or claim(client, capture)
    current = client.get(f"{API}/captures/{capture['id']}").json()
    return client.post(
        f"{API}/captures/{capture['id']}/proposal",
        json={"expected_version": current["version"], "expected_generation": current["processing"]["generation"], "lease_token": lease["lease_token"], "slots": slot_values, **extra},
    )


def reviewed(client, text, slot_values, *, model_confidence=None, **kw):
    capture = typed_voice(client, text, **kw)
    response = propose(client, capture, slot_values, **({"model_confidence": model_confidence} if model_confidence else {}))
    assert response.status_code == 200, response.text
    return response.json()


def accept(client, capture, *, overrides=None, confirm_overdue=None, key=None):
    body = {"expected_version": capture["version"], "expected_generation": capture["processing"]["generation"]}
    if overrides is not None:
        body["overrides"] = overrides
    if confirm_overdue is not None:
        body["confirm_overdue"] = confirm_overdue
    return client.post(f"{API}/captures/{capture['id']}/proposal/accept", json=body, headers={"Idempotency-Key": key or uuid.uuid4().hex})


def history(client, capture_id):
    return client.get(f"{API}/captures/{capture_id}/history").json()["items"]


@pytest.fixture(scope="module")
def world(client):
    categories = {c["slug"]: c["id"] for c in client.get(f"{API}/categories").json()}
    folder = client.post(f"{API}/items", json={"item_type": "folder", "title": "Voice Zeta Databases", "category_id": categories["learning"]}).json()
    project = client.post(f"{API}/items", json={"item_type": "project", "title": "Voice Kitchen Overhaul", "category_id": categories["projects"]}).json()
    return {"categories": categories, "folder": folder, "project": project}


# ---- capabilities -----------------------------------------------------------------------------
def test_capabilities_default_off_and_no_store(client, voice_disabled):
    response = client.get(f"{API}/capabilities")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    voice_caps = response.json()["voice_commands"]
    assert voice_caps["enabled"] is False and voice_caps["accepts_audio"] is False and voice_caps["reason"] == "voice_disabled"
    assert voice_caps["auto_apply_intents"] == [] and voice_caps["allowed_intents"] == ["create_note", "create_task"]


def test_capabilities_reflect_env_settings(client, voice):
    caps = client.get(f"{API}/capabilities").json()
    assert caps["voice_commands"]["enabled"] is True and caps["voice_commands"]["max_seconds"] == 60
    assert "video/webm" in caps["voice_commands"]["accepted_mime_types"]
    assert set(caps["queue"]) == {"pending_voice", "oldest_pending_age_s"}


def test_auto_apply_setting_cannot_be_enabled_in_this_release(monkeypatch):
    from backend.config import Settings

    monkeypatch.setenv("TRACEBACK_VOICE_AUTO_APPLY_INTENTS", "create_task")
    with pytest.raises(ValueError, match="review-first"):
        Settings()  # type: ignore[call-arg]


# ---- atomic idempotent ingest -------------------------------------------------------------------
def asset_files(settings) -> set[str]:
    return set(os.listdir(settings.asset_dir))


def test_ingest_saves_audio_and_capture_atomically_with_timestamps(client, voice):
    captured = now_ist() - timedelta(seconds=3)
    data = wav_bytes()
    response = ingest(client, data, captured=captured, duration_ms=1234, allowed_intent=["create_task"], entry_point="tasks")
    assert response.status_code == 201, response.text
    capture = response.json()
    assert capture["source_type"] == "audio" and len(capture["asset_ids"]) == 1
    assert capture["processing"]["state"] == "pending" and capture["processing"]["transcript"] is None
    assert capture["timestamp_origin"] == "client_supplied" and capture["source_timezone"] == "Asia/Kolkata"
    meta = capture["metadata"]
    assert meta["processing_profile"] == "voice_command" and meta["entry_point"] == "tasks" and meta["allowed_intents"] == ["create_task"]
    assert meta["observed_captured_at"] == captured.isoformat()
    assert datetime.fromisoformat(capture["captured_at"]) == captured and capture["created_at"] != capture["captured_at"]
    asset = client.get(f"{API}/assets/{capture['asset_ids'][0]}").json()
    assert asset["sha256"] == hashlib.sha256(data).hexdigest() and asset["byte_size"] == len(data)
    assert client.get(f"{API}/assets/{capture['asset_ids'][0]}/content").content == data
    assert [r["change_type"] for r in history(client, capture["id"])] == ["created"]
    inbox = client.get(f"{API}/inbox").json()
    assert capture["id"] in [c["id"] for c in inbox["captures"]]


def test_same_key_same_bytes_replays_one_asset_and_one_capture(client, voice):
    settings = current_settings()
    data, key = wav_bytes(), uuid.uuid4().hex
    before = asset_files(settings)
    first = ingest(client, data, key)
    second = ingest(client, data, key)
    assert first.status_code == second.status_code == 201 and first.json()["id"] == second.json()["id"]
    assert len(asset_files(settings) - before) == 1


def test_same_key_different_payload_conflicts(client, voice):
    key = uuid.uuid4().hex
    assert ingest(client, wav_bytes(), key).status_code == 201
    other = ingest(client, wav_bytes(), key)
    assert other.status_code == 409 and other.json()["error"]["code"] == "idempotency_conflict"


def test_idempotency_key_is_required(client, voice):
    response = ingest(client, key=False)
    assert response.status_code == 400 and response.json()["error"]["code"] == "idempotency_key_required"


def test_rejected_ingests_leave_no_file_and_no_capture(client, voice):
    settings = current_settings()
    before, captures_before = asset_files(settings), len(client.get(f"{API}/captures", params={"limit": 100}).json()["items"])
    data = wav_bytes()
    bad_digest = ingest(client, data, sha256="0" * 64)
    assert bad_digest.status_code == 422 and bad_digest.json()["error"]["code"] == "digest_mismatch"
    short = ingest(client, data, size=len(data) + 5)
    assert short.status_code in (400, 422) and short.json()["error"]["code"] == "size_mismatch"
    long = ingest(client, data, size=len(data) - 5)
    assert long.status_code in (400, 422) and long.json()["error"]["code"] == "size_mismatch"
    not_audio = b"%PDF-1.4 not audio at all " * 40
    unsupported = ingest(client, not_audio)
    assert unsupported.status_code == 415 and unsupported.json()["error"]["code"] == "unsupported_media"
    assert asset_files(settings) == before
    assert len(client.get(f"{API}/captures", params={"limit": 100}).json()["items"]) == captures_before


def test_oversize_and_overlong_are_rejected_before_any_write(client):
    settings_override(voice_commands_enabled=True, voice_min_free_disk_bytes=0, voice_max_upload_bytes=2048)
    try:
        settings = current_settings()
        before = asset_files(settings)
        big = wav_bytes("x" * 1500)
        assert len(big) > 2048
        response = ingest(client, big)
        assert response.status_code == 413 and response.json()["error"]["code"] == "upload_too_large"
        long = ingest(client, wav_bytes("s"), duration_ms=10 * 60 * 1000)
        assert long.status_code == 422 and long.json()["error"]["code"] == "duration_too_long"
        assert asset_files(settings) == before
    finally:
        clear_override()


def test_low_disk_preflight_returns_507_without_writing(client):
    settings_override(voice_commands_enabled=True, voice_min_free_disk_bytes=10**18)
    try:
        before = asset_files(current_settings())
        response = ingest(client)
        assert response.status_code == 507 and response.json()["error"]["code"] == "insufficient_storage"
        assert asset_files(current_settings()) == before
        assert client.get(f"{API}/capabilities").json()["voice_commands"]["low_disk"] is True
    finally:
        clear_override()


def test_enospc_mid_write_removes_temp_file_and_returns_507(client, voice, monkeypatch):
    settings = current_settings()
    before = asset_files(settings)

    def full_disk(_fd):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr("backend.voice.os.fsync", full_disk)
    response = ingest(client)
    assert response.status_code == 507
    monkeypatch.undo()
    assert asset_files(settings) == before


def test_database_failure_after_file_replace_unlinks_the_file(client, voice, monkeypatch):
    settings = current_settings()
    before = asset_files(settings)

    def boom(*_a, **_k):
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr("backend.voice.finish_action", boom)
    with pytest.raises(RuntimeError):
        ingest(client)
    monkeypatch.undo()
    assert asset_files(settings) == before
    captures = client.get(f"{API}/captures", params={"limit": 100, "source_type": "audio"}).json()["items"]
    assert all(c["asset_ids"] for c in captures)  # no capture without its audio


def test_duplicate_recording_without_key_points_at_existing_capture(client, voice):
    data = wav_bytes()
    first = ingest(client, data)
    duplicate = ingest(client, data)
    assert duplicate.status_code == 409
    error = duplicate.json()["error"]
    assert error["code"] == "duplicate_recording" and error["details"]["capture_id"] == first.json()["id"]


def test_ingest_disabled_returns_403_and_writes_nothing(client, voice_disabled):
    before = asset_files(current_settings())
    response = ingest(client)
    assert response.status_code == 403 and response.json()["error"]["code"] == "capability_disabled"
    assert asset_files(current_settings()) == before


def test_twenty_concurrent_same_key_requests_create_one_capture(client, voice, live_server):  # noqa: F811
    settings = current_settings()
    data, key = wav_bytes(), uuid.uuid4().hex
    before = asset_files(settings)
    params = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "captured_at": now_ist().isoformat(), "source_timezone": "Asia/Kolkata", "entry_point": "global"}
    headers = {"Authorization": f"Bearer {TOKEN}", "Idempotency-Key": key, "Content-Type": "audio/wav"}

    def send(_):
        return httpx.post(f"{live_server}{API}/voice-captures", params=params, content=data, headers=headers, timeout=30)

    with concurrent.futures.ThreadPoolExecutor(20) as pool:
        responses = list(pool.map(send, range(20)))
    assert {r.status_code for r in responses} == {201}, [r.text for r in responses if r.status_code != 201][:1]
    assert len({r.json()["id"] for r in responses}) == 1
    assert len(asset_files(settings) - before) == 1


def test_legacy_asset_upload_is_unchanged(client, voice):
    response = client.post(f"{API}/assets", params={"filename": "a.bin"}, content=b"abc", headers={"Content-Type": "application/octet-stream"})
    assert response.status_code == 201


# ---- typed voice capture profile ---------------------------------------------------------------
def test_typed_voice_capture_requires_anchor_and_profile_metadata(client, voice):
    missing = client.post(f"{API}/captures", json={"source_type": "typed", "raw_text": "hi", "metadata": {"processing_profile": "voice_command"}})
    assert missing.status_code == 422
    audio = client.post(f"{API}/captures", json={"source_type": "audio", "asset_ids": [str(uuid.uuid4())], "captured_at": now_ist().isoformat(), "source_timezone": "Asia/Kolkata", "timestamp_origin": "client_supplied", "metadata": {"processing_profile": "voice_command"}})
    assert audio.status_code == 422  # audio must use /voice-captures
    stray = client.post(f"{API}/captures", json={"source_type": "typed", "raw_text": "hi", "metadata": {"entry_point": "global"}})
    assert stray.status_code == 422
    capture = typed_voice(client, "Remind me to call mom")
    assert capture["metadata"]["observed_captured_at"]


def test_typed_voice_capture_is_refused_while_disabled(client, voice_disabled):
    response = client.post(f"{API}/captures", json={"source_type": "typed", "raw_text": "hi", "captured_at": now_ist().isoformat(), "source_timezone": "Asia/Kolkata", "timestamp_origin": "client_supplied", "metadata": {"processing_profile": "voice_command", "entry_point": "mcp_typed"}})
    assert response.status_code == 403 and response.json()["error"]["code"] == "capability_disabled"


# ---- transcript checkpoint and version mechanics ---------------------------------------------------
def test_transcript_checkpoint_does_not_bump_version_or_write_a_revision(client, voice):
    capture = ingest(client).json()
    lease = claim(client, capture)
    revisions = len(history(client, capture["id"]))
    response = client.post(f"{API}/captures/{capture['id']}/transcript", json={"expected_generation": 1, "lease_token": lease["lease_token"], "transcript": "Remind me to call mom", "stt_model_id": "ggml-small.bin", "duration_ms": 2100})
    assert response.status_code == 200 and response.json()["transcript_saved"] is True
    after = client.get(f"{API}/captures/{capture['id']}").json()
    assert after["version"] == capture["version"] and after["processing"]["transcript"] == "Remind me to call mom"
    assert len(history(client, capture["id"])) == revisions
    # the version read after /claim is still valid for /proposal
    proposed = propose(client, after, slots(intent="create_task", title="call mom"), lease=lease)
    assert proposed.status_code == 200 and proposed.json()["version"] == capture["version"] + 1
    revision = history(client, capture["id"])[0]
    assert revision["change_type"] == "proposal" and revision["changes"]["transcript_sha256"] == hashlib.sha256(b"Remind me to call mom").hexdigest()


def test_fail_preserves_a_checkpointed_transcript_and_a_stale_lease_cannot_checkpoint(client, voice):
    capture = ingest(client).json()
    lease = claim(client, capture)
    client.post(f"{API}/captures/{capture['id']}/transcript", json={"expected_generation": 1, "lease_token": lease["lease_token"], "transcript": "keep me"})
    failed = client.post(f"{API}/captures/{capture['id']}/fail", json={"expected_generation": 1, "lease_token": lease["lease_token"], "error_code": "InterpretationError", "error_message": "qwen down"})
    assert failed.status_code == 200 and failed.json()["processing"]["transcript"] == "keep me"
    late = client.post(f"{API}/captures/{capture['id']}/transcript", json={"expected_generation": 1, "lease_token": lease["lease_token"], "transcript": "late"})
    assert late.status_code == 409
    current = failed.json()
    retried = client.post(f"{API}/captures/{capture['id']}/retry", json={"expected_version": current["version"], "expected_generation": 1})
    assert retried.status_code == 200 and retried.json()["processing"]["transcript"] == "keep me"  # LLM-only retry can reuse it


def test_no_speech_checkpoint_fails_the_capture_and_keeps_audio_in_inbox(client, voice):
    capture = ingest(client).json()
    lease = claim(client, capture)
    response = client.post(f"{API}/captures/{capture['id']}/transcript", json={"expected_generation": 1, "lease_token": lease["lease_token"], "no_speech": True})
    assert response.status_code == 200 and response.json()["state"] == "failed"
    failed = client.get(f"{API}/captures/{capture['id']}").json()
    assert failed["processing"]["state"] == "failed" and failed["processing"]["error_code"] == "no_speech" and failed["asset_ids"] == capture["asset_ids"]
    assert capture["id"] in [c["id"] for c in client.get(f"{API}/inbox").json()["captures"]]


def test_transcript_checkpoint_rejects_missing_text_and_other_profiles(client, voice):
    capture = ingest(client).json()
    lease = claim(client, capture)
    bad = client.post(f"{API}/captures/{capture['id']}/transcript", json={"expected_generation": 1, "lease_token": lease["lease_token"]})
    assert bad.status_code == 422
    plain = client.post(f"{API}/captures", json={"source_type": "typed", "raw_text": "plain"}).json()
    plain_lease = claim(client, plain)
    other = client.post(f"{API}/captures/{plain['id']}/transcript", json={"expected_generation": 1, "lease_token": plain_lease["lease_token"], "transcript": "x"})
    assert other.status_code == 422


# ---- proposals: trust boundary --------------------------------------------------------------------
@pytest.mark.parametrize(
    "forged",
    [{"warnings": []}, {"disposition": "auto_apply_eligible"}, {"grounded": True}, {"operation": {"type": "create"}}, {"destination_id": str(uuid.uuid4())}],
)
def test_processor_forged_top_level_fields_are_rejected(client, voice, forged):
    capture = typed_voice(client, "Remind me to call mom")
    lease = claim(client, capture)
    body = {"expected_version": capture["version"], "expected_generation": 1, "lease_token": lease["lease_token"], "slots": slots(intent="create_task", title="call mom"), **forged}
    assert client.post(f"{API}/captures/{capture['id']}/proposal", json=body).status_code == 422


@pytest.mark.parametrize("extra", [{"destination_id": str(uuid.uuid4())}, {"due_date": "2026-10-02"}, {"warnings": ["x"]}, {"category_id": "x"}])
def test_model_emitted_ids_dates_and_verdicts_inside_slots_are_rejected(client, voice, extra):
    capture = typed_voice(client, "Remind me to call mom")
    assert propose(client, capture, {**slots(intent="create_task", title="call mom"), **extra}).status_code == 422


def test_seed_note_utterance_is_recomputed_by_the_backend(client, voice, world):
    text = "Add a note called Normal forms in Voice Zeta Databases"
    capture = reviewed(client, text, slots(intent="create_note", title="Normal forms", destination_phrase="Voice Zeta Databases"), model_confidence="high")
    proposal = capture["processing"]["proposal"]
    assert capture["processing"]["state"] == "awaiting_review" and capture["resulting_item_ids"] == []
    destination = proposal["operation"]["destination"]
    assert destination["id"] == world["folder"]["id"] and destination["path"].startswith("Learning / ")
    assert proposal["disposition"] == "review" and proposal["policy_version"] == 1 and proposal["generation"] == 1
    assert proposal["proposal_sha256"] and proposal["model_confidence"] == "high"


def test_relative_date_uses_captured_at_anchor_not_receipt_time(client, voice):
    captured = now_ist() - timedelta(days=1, hours=2)  # spoken yesterday, ingested now
    text = "Remind me to file the form tomorrow at 5 PM"
    capture = typed_voice(client, text, captured=captured)
    response = propose(client, capture, slots(intent="create_task", title="file the form", date_phrase="tomorrow", time_phrase="5 PM"))
    proposal = response.json()["processing"]["proposal"]
    assert proposal["operation"]["due_date"] == (captured.date() + timedelta(days=1)).isoformat()
    assert proposal["operation"]["due_timezone"] == "Asia/Kolkata"
    assert "delayed_ingest" in proposal["warnings"] and proposal["resolution"]["anchor"]["skew_s"] > 300
    assert proposal["resolution"]["anchor"]["observed_captured_at"] == captured.isoformat()
    assert any(alt.get("anchor") == "receipt" for alt in proposal["resolution"]["date"]["alternatives"])


def test_restricted_launcher_and_capture_only_stay_awaiting_review_in_inbox(client, voice):
    restricted = reviewed(client, "Add a note called X", slots(intent="create_note", title="X"), allowed_intents=["create_task"], entry_point="tasks")
    only = reviewed(client, "Dad's birthday gift ideas", slots(intent="capture_only"))
    for capture, intent in ((restricted, "unsupported"), (only, "capture_only")):
        assert capture["processing"]["state"] == "awaiting_review" and capture["processing"]["proposal"]["intent"] == intent
        assert capture["processing"]["proposal"]["operation"] is None
    inbox_ids = [c["id"] for c in client.get(f"{API}/inbox").json()["captures"]]
    assert restricted["id"] in inbox_ids and only["id"] in inbox_ids
    for capture in (restricted, only):
        refused = accept(client, capture)
        assert refused.status_code == 422 and refused.json()["error"]["code"] == "nothing_to_accept"


def test_capture_only_becomes_a_note_only_via_save_as_and_resolves_once(client, voice):
    capture = reviewed(client, "Dad's birthday gift ideas", slots(intent="capture_only"))
    saved = client.post(
        f"{API}/captures/{capture['id']}/interpretations",
        json={"expected_version": capture["version"], "expected_generation": 1, "mode": "manual", "items": [{"kind": "create", "item": {"item_type": "note", "title": "Dad's birthday gift ideas", "content_md": "Dad's birthday gift ideas"}}]},
    )
    assert saved.status_code == 200 and saved.json()["capture"]["processing"]["state"] == "resolved"
    audit = history(client, capture["id"])[0]["changes"]["voice_audit"]
    assert audit["accept_path"] == "manual_interpretation" and audit["proposal_present"] is True and audit["edited_fields"] is None
    again = client.post(
        f"{API}/captures/{capture['id']}/interpretations",
        json={"expected_version": saved.json()["capture"]["version"], "expected_generation": 2, "mode": "manual", "items": [{"kind": "create", "item": {"item_type": "note", "title": "dup"}}]},
    )
    assert again.status_code == 409


# ---- accept, overrides, overdue, audit --------------------------------------------------------------
def test_accept_creates_exactly_one_placed_item_with_provenance_and_clean_audit(client, voice, world):
    capture = reviewed(client, "Add a note called Normal forms in Voice Zeta Databases", slots(intent="create_note", title="Normal forms", destination_phrase="Voice Zeta Databases"))
    response = accept(client, capture)
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["items"]) == 1 and result["capture"]["processing"]["state"] == "resolved"
    item = result["items"][0]
    assert item["item_type"] == "note" and item["title"] == "Normal forms" and item["content_md"] == ""
    assert any(r["to_item_id"] == world["folder"]["id"] and r["relation"] == "part_of" for r in item["relations"])
    assert client.get(f"{API}/items/{item['id']}/sources").json()[0]["capture_id"] == capture["id"]
    assert result["capture"]["processing"]["generation"] == 2  # generation bumped: late automation is fenced
    audit = history(client, capture["id"])[0]["changes"]["voice_audit"]
    assert audit["accept_path"] == "accept_endpoint" and audit["proposal_present"] is True and audit["edited_fields"] == []
    assert audit["accepted"]["destination"]["id"] == world["folder"]["id"] and audit["accepted"]["content_length"] == 0
    assert audit["accepted"]["content_sha256"] == hashlib.sha256(b"").hexdigest() and audit["overdue_confirmed"] is False
    assert audit["proposal_sha256"] == capture["processing"]["proposal"]["proposal_sha256"]


def test_double_accept_creates_one_item(client, voice):
    capture = reviewed(client, "Add a note called Twice", slots(intent="create_note", title="Twice"))
    key = uuid.uuid4().hex
    first, replay = accept(client, capture, key=key), accept(client, capture, key=key)
    assert first.status_code == replay.status_code == 200 and first.json()["items"][0]["id"] == replay.json()["items"][0]["id"]
    second_click = accept(client, capture)
    assert second_click.status_code == 409
    assert set(second_click.json()["error"]["details"]) >= {"version", "generation", "state"}


def test_overrides_are_validated_and_audited_by_the_server(client, voice, world):
    capture = reviewed(client, "Remind me to call the plumber tomorrow", slots(intent="create_task", title="call the plumber", date_phrase="tomorrow"))
    overrides = {"title": "Call the plumber about the sink", "due_date": None, "destination": {"kind": "project", "id": world["project"]["id"]}}
    response = accept(client, capture, overrides=overrides)
    assert response.status_code == 200, response.text
    audit = history(client, capture["id"])[0]["changes"]["voice_audit"]
    assert set(audit["edited_fields"]) == {"title", "due_date", "destination"}
    assert response.json()["items"][0]["due_date"] is None
    invalid = accept(client, reviewed(client, "Remind me to call the vet", slots(intent="create_task", title="call the vet")), overrides={"due_time": "17:00:00"})
    assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "invalid_input"
    forged = client.post(f"{API}/captures/{capture['id']}/proposal/accept", json={"expected_version": 1, "expected_generation": 1, "edited_fields": []})
    assert forged.status_code == 422


def test_switching_note_to_task_uses_intent_in_audit(client, voice):
    capture = reviewed(client, "Add Vendor comparison in Voice Zeta Databases", slots(intent="create_note", title="Vendor comparison", destination_phrase="Voice Zeta Databases"))
    assert "intent_inferred" in capture["processing"]["proposal"]["warnings"]
    response = accept(client, capture, overrides={"item_type": "task"})
    assert response.status_code == 200 and response.json()["items"][0]["item_type"] == "task"
    assert {"item_type", "intent"} <= set(history(client, capture["id"])[0]["changes"]["voice_audit"]["edited_fields"])


def test_overdue_deadline_requires_explicit_confirmation(client, voice):
    capture = reviewed(client, "Remind me to pay rent yesterday", slots(intent="create_task", title="pay rent", date_phrase="yesterday"))
    assert "deadline_past" in capture["processing"]["proposal"]["warnings"]
    refused = accept(client, capture)
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "overdue_confirmation_required"
    assert refused.json()["error"]["details"]["overdue_by_seconds"] > 0
    assert client.get(f"{API}/captures/{capture['id']}").json()["processing"]["state"] == "awaiting_review"
    confirmed = accept(client, capture, confirm_overdue=True)
    assert confirmed.status_code == 200 and confirmed.json()["items"][0]["overdue"] is True
    assert history(client, capture["id"])[0]["changes"]["voice_audit"]["overdue_confirmed"] is True


def test_manual_paths_keep_the_old_no_past_deadline_rule(client, voice):
    yesterday = (now_ist().date() - timedelta(days=1)).isoformat()
    assert client.post(f"{API}/items", json={"item_type": "task", "title": "Old", "due_date": yesterday}).status_code == 201


def test_date_only_today_is_not_overdue(client, voice):
    capture = reviewed(client, "Remind me to stretch today", slots(intent="create_task", title="stretch", date_phrase="today"))
    assert accept(client, capture).status_code == 200


def test_stale_version_conflict_carries_refetch_details_and_writes_nothing(client, voice):
    capture = reviewed(client, "Add a note called Stale check", slots(intent="create_note", title="Stale check"))
    stale = client.post(f"{API}/captures/{capture['id']}/proposal/accept", json={"expected_version": capture["version"] - 1, "expected_generation": 1})
    error = stale.json()["error"]
    assert stale.status_code == 409 and error["code"] == "version_conflict"
    assert error["details"]["version"] == capture["version"] and error["details"]["generation"] == 1
    assert error["details"]["state"] == "awaiting_review" and error["details"]["proposal_sha256"] == capture["processing"]["proposal"]["proposal_sha256"]
    assert client.get(f"{API}/captures/{capture['id']}").json()["resulting_item_ids"] == []


def test_destination_archived_after_proposal_conflicts_without_partial_write(client, voice, world):
    folder = client.post(f"{API}/items", json={"item_type": "folder", "title": "Voice Ephemeral Shelf", "category_id": world["categories"]["learning"]}).json()
    capture = reviewed(client, "Add a note called Shelf in Voice Ephemeral Shelf", slots(intent="create_note", title="Shelf", destination_phrase="Voice Ephemeral Shelf"))
    client.post(f"{API}/items/{folder['id']}/archive", json={"expected_version": folder["version"]})
    response = accept(client, capture)
    assert response.status_code == 409 and response.json()["error"]["code"] == "destination_changed"
    assert client.get(f"{API}/captures/{capture['id']}").json()["processing"]["state"] == "awaiting_review"


def test_manual_user_action_fences_a_late_processor_submission(client, voice):
    capture = typed_voice(client, "Add a note called Race")
    lease = claim(client, capture)
    manual = client.post(
        f"{API}/captures/{capture['id']}/interpretations",
        json={"expected_version": capture["version"], "expected_generation": 1, "mode": "manual", "items": [{"kind": "create", "item": {"item_type": "note", "title": "Race", "content_md": "typed"}}]},
    )
    assert manual.status_code == 200
    late = client.post(f"{API}/captures/{capture['id']}/proposal", json={"expected_version": capture["version"], "expected_generation": 1, "lease_token": lease["lease_token"], "slots": slots(title="Race")})
    assert late.status_code == 409
    no_proposal = history(client, capture["id"])[0]["changes"]["voice_audit"]
    assert no_proposal["proposal_present"] is False and no_proposal["edited_fields"] is None


def test_processor_mode_interpretation_is_refused_for_voice_review_first(client, voice):
    capture = typed_voice(client, "Add a note called Auto")
    lease = claim(client, capture)
    response = client.post(
        f"{API}/captures/{capture['id']}/interpretations",
        json={"expected_version": capture["version"], "expected_generation": 1, "mode": "processor", "lease_token": lease["lease_token"], "items": [{"kind": "create", "item": {"item_type": "note", "title": "Auto"}}]},
    )
    assert response.status_code == 422 and response.json()["error"]["code"] == "auto_apply_unavailable"


def test_manual_voice_interpretation_allows_only_one_note_or_task(client, voice):
    capture = typed_voice(client, "Two things")
    items = [{"kind": "create", "item": {"item_type": "note", "title": "a"}}, {"kind": "create", "item": {"item_type": "note", "title": "b"}}]
    response = client.post(f"{API}/captures/{capture['id']}/interpretations", json={"expected_version": capture["version"], "expected_generation": 1, "mode": "manual", "items": items})
    assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_interpretation"


def test_archiving_an_awaiting_review_capture_records_the_discard(client, voice):
    capture = reviewed(client, "Add a note called Discard me", slots(intent="create_note", title="Discard me"))
    archived = client.post(f"{API}/captures/{capture['id']}/archive", json={"expected_version": capture["version"]})
    assert archived.status_code == 200
    changes = history(client, capture["id"])[0]["changes"]
    assert changes == {"proposal_generation": 1, "discarded_after_proposal": True}


# ---- corrections --------------------------------------------------------------------------------
def test_transcript_correction_requeues_at_a_new_generation_and_clears_the_proposal(client, voice):
    capture = reviewed(client, "Add a note called Mishaerd", slots(intent="create_note", title="Mishaerd"))
    corrected = client.post(f"{API}/captures/{capture['id']}/corrections", json={"expected_version": capture["version"], "transcript_text": "Add a note called Misheard"})
    assert corrected.status_code == 200
    body = corrected.json()
    assert body["processing"]["state"] == "pending" and body["processing"]["generation"] == 2 and body["processing"]["proposal"] is None
    assert body["corrections"]["transcript_text"] == "Add a note called Misheard"
    stale = client.post(f"{API}/captures/{capture['id']}/corrections", json={"expected_version": capture["version"], "transcript_text": "x"})
    assert stale.status_code == 409  # a correction against a stale proposal conflicts on version
    replay = propose(client, body, slots(intent="create_note", title="Misheard"))
    assert replay.status_code == 200 and replay.json()["processing"]["proposal"]["operation"]["title"] == "Misheard"


def test_captured_at_correction_requeues_and_preserves_the_observed_time(client, voice):
    capture = reviewed(client, "Remind me to call mom tomorrow", slots(intent="create_task", title="call mom", date_phrase="tomorrow"))
    fixed = (now_ist() - timedelta(days=3)).isoformat()
    corrected = client.post(f"{API}/captures/{capture['id']}/corrections", json={"expected_version": capture["version"], "captured_at": fixed}).json()
    assert corrected["processing"]["state"] == "pending" and corrected["metadata"]["observed_captured_at"] == capture["metadata"]["observed_captured_at"]
    proposal = propose(client, corrected, slots(intent="create_task", title="call mom", date_phrase="tomorrow")).json()["processing"]["proposal"]
    assert proposal["resolution"]["anchor"]["captured_at"] == fixed
    assert proposal["resolution"]["anchor"]["observed_captured_at"] == capture["metadata"]["observed_captured_at"]


def test_transcript_text_is_rejected_for_non_voice_captures(client, voice):
    plain = client.post(f"{API}/captures", json={"source_type": "typed", "raw_text": "plain"}).json()
    response = client.post(f"{API}/captures/{plain['id']}/corrections", json={"expected_version": 1, "transcript_text": "x"})
    assert response.status_code == 422


# ---- disabled behavior and the manual escape hatch ---------------------------------------------------------
def test_stranded_pending_audio_is_completed_by_hand_while_voice_is_disabled(client, voice):
    """Manual escape hatch: no worker, requeue, or transcript is needed, and a late processor call is fenced."""
    stranded = ingest(client).json()
    lease = claim(client, stranded)
    clear_override()
    settings_override(voice_commands_enabled=False)  # the operator restarts the API with voice off
    assert client.get(f"{API}/capabilities").json()["voice_commands"]["enabled"] is False
    saved = client.post(
        f"{API}/captures/{stranded['id']}/interpretations",
        json={"expected_version": stranded["version"], "expected_generation": 1, "mode": "manual", "transcript": "typed by me", "items": [{"kind": "create", "item": {"item_type": "task", "title": "Typed by me", "content_md": "typed by me"}}]},
    )
    assert saved.status_code == 200 and saved.json()["capture"]["processing"]["generation"] == 2
    assert saved.json()["capture"]["processing"]["transcript"] == "typed by me"
    late = client.post(f"{API}/captures/{stranded['id']}/transcript", json={"expected_generation": 1, "lease_token": lease["lease_token"], "transcript": "late worker"})
    assert late.status_code == 409
    note = ingest_stranded_note(client)
    manual_note = client.post(
        f"{API}/captures/{note['id']}/interpretations",
        json={"expected_version": note["version"], "expected_generation": 1, "mode": "manual", "items": [{"kind": "create", "item": {"item_type": "note", "title": "By hand", "content_md": "by hand"}}]},
    )
    assert manual_note.status_code == 200


def ingest_stranded_note(client):
    """Create a pending voice capture the way it exists after voice was switched off (audio saved, no transcript)."""
    clear_override()
    settings_override(voice_commands_enabled=True, voice_min_free_disk_bytes=0)
    try:
        return ingest(client).json()
    finally:
        clear_override()
        settings_override(voice_commands_enabled=False)


def test_disabled_mode_skips_voice_in_claim_next_and_refuses_retry(client, voice):
    drain_claimable_captures(client)
    failed_source = ingest(client).json()
    lease = claim(client, failed_source)
    client.post(f"{API}/captures/{failed_source['id']}/fail", json={"expected_generation": 1, "lease_token": lease["lease_token"], "error_code": "TranscriptionError", "error_message": "x"})
    failed = client.get(f"{API}/captures/{failed_source['id']}").json()
    waiting = typed_voice(client, "Remind me to wait")
    clear_override()
    settings_override(voice_commands_enabled=False)
    assert client.post(f"{API}/captures/claim-next", json={}).status_code == 204  # the pending voice capture is skipped
    retry = client.post(f"{API}/captures/{failed['id']}/retry", json={"expected_version": failed["version"], "expected_generation": 1})
    assert retry.status_code == 409 and retry.json()["error"]["code"] == "capability_disabled"
    assert client.get(f"{API}/captures/{waiting['id']}").json()["processing"]["state"] == "pending"


def test_disabled_mode_blocks_transcript_correction_and_claiming_but_not_manual_accept(client, voice):
    capture = reviewed(client, "Add a note called Still works", slots(intent="create_note", title="Still works"))
    other = ingest(client).json()
    clear_override()
    settings_override(voice_commands_enabled=False)
    correction = client.post(f"{API}/captures/{capture['id']}/corrections", json={"expected_version": capture["version"], "transcript_text": "changed"})
    assert correction.status_code == 409 and correction.json()["error"]["code"] == "capability_disabled"
    claim_by_id = client.post(f"{API}/captures/{other['id']}/claim", json={"expected_generation": 1})
    assert claim_by_id.status_code == 403 and claim_by_id.json()["error"]["code"] == "capability_disabled"
    accepted = accept(client, capture)
    assert accepted.status_code == 200 and accepted.json()["capture"]["processing"]["state"] == "resolved"
    archived = client.post(f"{API}/captures/{other['id']}/archive", json={"expected_version": other["version"]})
    assert archived.status_code == 200  # discard always works


# ---- claim-next fairness --------------------------------------------------------------------------
def make_plain(client, text="plain"):
    return client.post(f"{API}/captures", json={"source_type": "typed", "raw_text": text}).json()


def test_claim_next_is_idle_204_and_claims_without_bumping_version(client, voice):
    drain_claimable_captures(client)
    assert client.post(f"{API}/captures/claim-next", json={}).status_code == 204
    capture = typed_voice(client, "Remind me to call mom")
    response = client.post(f"{API}/captures/claim-next", json={"lease_seconds": 60})
    body = response.json()
    assert response.status_code == 200 and body["capture_id"] == capture["id"] and body["profile"] == "voice_command"
    assert body["version"] == capture["version"] and client.get(f"{API}/captures/{capture['id']}").json()["version"] == capture["version"]
    assert client.post(f"{API}/captures/claim-next", json={}).status_code == 204  # leased, so nothing else is claimable


def test_claim_next_prefers_voice_but_never_starves_older_work(client, voice):
    drain_claimable_captures(client)
    reset = make_plain(client, "resets the voice streak")
    assert client.post(f"{API}/captures/claim-next", json={}).json()["capture_id"] == reset["id"]
    older = [make_plain(client, f"older {i}") for i in range(2)]
    voices = [typed_voice(client, f"Remind me {i}") for i in range(4)]
    order = []
    for _ in range(6):
        body = client.post(f"{API}/captures/claim-next", json={}).json()
        order.append(body["capture_id"])
    voice_ids, older_ids = {v["id"] for v in voices}, {o["id"] for o in older}
    assert order[0] in voice_ids and order[1] in voice_ids  # voice preferred...
    assert order[2] in older_ids  # ...but at most 2 consecutive voice claims while older non-voice work waits
    assert set(order) == voice_ids | older_ids


def test_claim_next_aging_beats_voice_preference(client):
    settings_override(voice_commands_enabled=True, voice_min_free_disk_bytes=0, voice_queue_aging_s=1)
    try:
        drain_claimable_captures(client)
        older = make_plain(client, "aged")
        typed_voice(client, "Remind me later")
        import time

        time.sleep(1.2)
        body = client.post(f"{API}/captures/claim-next", json={}).json()
        assert body["capture_id"] == older["id"]
    finally:
        clear_override()


def test_claim_next_skips_voice_when_disabled_and_still_serves_other_profiles(client, voice_disabled):
    drain_claimable_captures(client)
    plain = make_plain(client)
    body = client.post(f"{API}/captures/claim-next", json={}).json()
    assert body["capture_id"] == plain["id"]
    settings_override(voice_commands_enabled=True, voice_min_free_disk_bytes=0)
    typed_voice(client, "hold on")
    settings_override(voice_commands_enabled=False)
    assert client.post(f"{API}/captures/claim-next", json={}).status_code == 204


def test_no_double_claim_under_concurrent_callers(client, voice, live_server):  # noqa: F811
    drain_claimable_captures(client)
    for i in range(3):
        typed_voice(client, f"Remind me {i}")
    headers = {"Authorization": f"Bearer {TOKEN}"}

    def send(_):
        return httpx.post(f"{live_server}{API}/captures/claim-next", json={}, headers=headers, timeout=30)

    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        responses = list(pool.map(send, range(8)))
    claimed = [r.json()["capture_id"] for r in responses if r.status_code == 200]
    assert len(claimed) == len(set(claimed)) == 3 and sum(r.status_code == 204 for r in responses) == 5
