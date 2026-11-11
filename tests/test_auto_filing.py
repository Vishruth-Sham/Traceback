"""Auto-filing: classified pieces become one atomic, undoable plan.

Unit tests cover the planner (model output validation and the per-intent
workflow templates) and the Claude provider switch, with the model stubbed.
API tests run the backend side for real: a processor interpretation that
mixes create, append and log steps, and the one-step undo of that filing.
"""
import json
import sys
import types
import uuid

import pytest

import processor.planner as planner
from processor.config import ProcessorSettings
from processor.errors import InterpretationError
from processor.planner import build_operations, extract_pieces

CATEGORY = str(uuid.uuid4())
PROJECT = str(uuid.uuid4())
FOLDER = str(uuid.uuid4())
LOCATIONS = [
    {"kind": "category", "id": CATEGORY, "title": "Personal", "path": "Personal", "category_id": CATEGORY, "version": None},
    {"kind": "project", "id": PROJECT, "title": "Traceback", "path": "Work / Traceback", "category_id": CATEGORY, "version": 4},
    {"kind": "folder", "id": FOLDER, "title": "Recipes", "path": "Personal / Recipes", "category_id": CATEGORY, "version": 2},
]
CAPTURE = {"captured_at": "2026-11-11T09:00:00+00:00", "source_timezone": "Asia/Kolkata"}


def piece(intent, title, **fields):
    return {
        "intent": intent,
        "title": title,
        "content_md": fields.pop("content_md", ""),
        "destination_kind": None,
        "destination_id": None,
        "target_id": None,
        "due_date": None,
        "due_time": None,
        "due_timezone": None,
        "confidence": "high",
        **fields,
    }


# --- workflow templates -------------------------------------------------------


def test_worked_example_becomes_append_task_and_log():
    pieces = [
        piece("update", "API refactor done", content_md="Finished the API refactor", target_id=PROJECT),
        piece("task", "Write tests", destination_kind="project", destination_id=PROJECT, due_date="2026-11-12"),
        piece("log", "Run", content_md="Had a great run this morning"),
    ]
    operations = build_operations(pieces, LOCATIONS, CAPTURE)
    assert [op["kind"] for op in operations] == ["append", "create", "log"]
    append, task, log = operations
    assert append == {
        "kind": "append",
        "item_id": PROJECT,
        "expected_version": 4,
        "content_md": "**2026-11-11**\n- Finished the API refactor",
        "intent": "update",
        "confidence": "high",
    }
    assert task["project_id"] == PROJECT and task["project_expected_version"] == 4
    assert task["item"]["category_id"] is None and task["item"]["due_date"] == "2026-11-12"
    assert log == {"kind": "log", "text": "Had a great run this morning", "at": CAPTURE["captured_at"], "intent": "log", "confidence": "high"}


def test_note_goes_to_folder_or_category_and_unknown_place_to_inbox():
    folder_note, category_note, lost_note = build_operations(
        [
            piece("note", "Dal recipe", destination_kind="folder", destination_id=FOLDER),
            piece("note", "Gift idea", destination_kind="category", destination_id=CATEGORY),
            piece("note", "Stray", destination_kind="folder", destination_id=str(uuid.uuid4())),
        ],
        LOCATIONS,
        CAPTURE,
    )
    assert folder_note["folder_id"] == FOLDER and folder_note["folder_expected_version"] == 2
    assert category_note["item"]["category_id"] == CATEGORY and "folder_id" not in category_note
    assert lost_note["item"]["category_id"] is None and lost_note["confidence"] == "low"


def test_updates_to_one_project_merge_and_unknown_target_becomes_note():
    operations = build_operations(
        [
            piece("update", "a", content_md="Shipped search", target_id=PROJECT, confidence="high"),
            piece("update", "b", content_md="Fixed login", target_id=PROJECT, confidence="medium"),
            piece("update", "Other thing moved", content_md="Moved", target_id=str(uuid.uuid4())),
        ],
        LOCATIONS,
        CAPTURE,
    )
    merged, fallback = operations
    assert merged["content_md"] == "**2026-11-11**\n- Shipped search\n- Fixed login"
    assert merged["confidence"] == "medium"
    assert fallback["kind"] == "create" and fallback["item"]["item_type"] == "note"
    assert fallback["intent"] == "note" and fallback["confidence"] == "low"


def test_new_project_with_existing_name_becomes_update():
    [operation] = build_operations([piece("project", "traceback", content_md="Start mobile app")], LOCATIONS, CAPTURE)
    assert operation["kind"] == "append" and operation["item_id"] == PROJECT


def test_new_project_inside_project_uses_that_projects_category():
    [operation] = build_operations(
        [piece("project", "Garden", destination_kind="project", destination_id=PROJECT)], LOCATIONS, CAPTURE
    )
    assert operation["item"] == {"item_type": "project", "title": "Garden", "content_md": "", "category_id": CATEGORY}
    assert "project_id" not in operation


# --- model output ---------------------------------------------------------------


def _settings(**overrides):
    return ProcessorSettings(**overrides)


def test_extract_pieces_retries_invalid_output(monkeypatch):
    replies = [
        "not json",
        json.dumps({"pieces": [piece("task", "Call mum", due_date="2026-11-12T17:00:00+05:30", due_time="17:00:00", due_timezone="+05:30")]}),
    ]
    seen = []

    def fake(messages, settings):
        seen.append(list(messages))
        return replies.pop(0)

    monkeypatch.setattr(planner, "_call_ollama", fake)
    pieces = extract_pieces("Call mum tomorrow at 5pm", {**CAPTURE, "locations": LOCATIONS}, settings=_settings())
    assert pieces[0]["due_date"] == "2026-11-12"
    assert pieces[0]["due_timezone"] == "Asia/Kolkata"
    assert len(seen) == 2 and "invalid" in seen[1][-1]["content"]
    prompt = json.loads(seen[0][1]["content"].split("Context:\n", 1)[1].split("\n\nCapture text", 1)[0])
    assert {entry["id"] for entry in prompt["locations"]} == {CATEGORY, PROJECT, FOLDER}


def test_extract_pieces_drops_due_fields_on_non_tasks_and_gives_up_eventually(monkeypatch):
    monkeypatch.setattr(planner, "_call_ollama", lambda m, s: json.dumps({"pieces": [piece("note", "Idea", due_date="2026-11-12")]}))
    [note] = extract_pieces("idea", CAPTURE, settings=_settings())
    assert note["due_date"] is None
    monkeypatch.setattr(planner, "_call_ollama", lambda m, s: json.dumps({"pieces": []}))
    with pytest.raises(InterpretationError):
        extract_pieces("idea", CAPTURE, settings=_settings())


def test_anthropic_provider_sends_system_prompt_and_reads_text(monkeypatch):
    calls = []

    class FakeMessages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(
                stop_reason="end_turn",
                content=[types.SimpleNamespace(type="thinking", thinking=""), types.SimpleNamespace(type="text", text='{"ok": 1}')],
            )

    class FakeClient:
        def __init__(self, timeout):
            self.messages = FakeMessages()
            self.beta = types.SimpleNamespace(messages=FakeMessages())

    fake_module = types.SimpleNamespace(
        Anthropic=FakeClient,
        APIConnectionError=type("E1", (Exception,), {}),
        RateLimitError=type("E2", (Exception,), {}),
        InternalServerError=type("E3", (Exception,), {}),
        APIStatusError=type("E4", (Exception,), {}),
    )
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)
    from processor.interpretation import _call_ollama

    settings = _settings(llm_provider="anthropic")
    reply = _call_ollama([{"role": "system", "content": "rules"}, {"role": "user", "content": "hi"}], settings)
    assert reply == '{"ok": 1}'
    [call] = calls
    assert call["system"] == "rules" and call["messages"] == [{"role": "user", "content": "hi"}]
    assert call["model"] == "claude-opus-5-5" and call["output_config"] == {"effort": "low"}
    assert call["fallbacks"] == "default"


# --- backend: apply and undo --------------------------------------------------------


def _capture(client, text="Filed by the planner"):
    response = client.post("/api/v1/captures", json={"source_type": "typed", "raw_text": text, "captured_at": "2031-05-04T09:00:00+00:00", "timestamp_origin": "client_supplied"})
    assert response.status_code == 201, response.text
    return response.json()


def _current_version(client, capture_id):
    return client.get(f"/api/v1/captures/{capture_id}").json()["version"]


def test_plan_with_log_applies_atomically_and_undoes_in_one_step(client):
    project = client.post("/api/v1/items", json={"item_type": "project", "title": f"Proj {uuid.uuid4()}", "content_md": "Start"}).json()
    capture = _capture(client)
    claim = client.post(f"/api/v1/captures/{capture['id']}/claim", json={"expected_generation": 1, "lease_seconds": 300})
    assert claim.status_code == 200, claim.text
    filed = client.post(
        f"/api/v1/captures/{capture['id']}/interpretations",
        json={
            "expected_version": _current_version(client, capture["id"]),
            "expected_generation": 1,
            "mode": "processor",
            "lease_token": claim.json()["lease_token"],
            "items": [
                {"kind": "append", "item_id": project["id"], "expected_version": project["version"], "content_md": "Refactor done", "intent": "update", "confidence": "high"},
                {"kind": "create", "item": {"item_type": "task", "title": "Write tests"}, "project_id": project["id"], "project_expected_version": project["version"], "intent": "task", "confidence": "medium"},
                {"kind": "log", "text": "Great run", "intent": "log", "confidence": "high"},
            ],
        },
    )
    assert filed.status_code == 200, filed.text
    result = filed.json()
    assert len(result["log_entry_ids"]) == 1
    task_id = next(item["id"] for item in result["items"] if item["item_type"] == "task")
    entries = client.get("/api/v1/log/days/2031-05-04").json()["entries"]
    assert [entry["text"] for entry in entries] == ["Great run"]
    history = client.get(f"/api/v1/captures/{capture['id']}/history").json()["items"]
    plan = next(row for row in history if row["change_type"] == "interpreted")["changes"]["plan"]
    assert [step["intent"] for step in plan] == ["update", "task", "log"]

    undo = client.post(f"/api/v1/captures/{capture['id']}/undo-filing", json={"expected_version": result["capture"]["version"]})
    assert undo.status_code == 200, undo.text
    body = undo.json()
    assert body["capture"]["processing"]["state"] == "failed"
    assert body["capture"]["processing"]["error_code"] == "filing_undone"
    assert client.get(f"/api/v1/items/{project['id']}").json()["content_md"] == "Start"
    assert client.get(f"/api/v1/items/{task_id}").json()["archived_at"] is not None
    assert client.get("/api/v1/log/days/2031-05-04").json()["entries"] == []

    again = client.post(f"/api/v1/captures/{capture['id']}/undo-filing", json={"expected_version": body["capture"]["version"]})
    assert again.status_code == 409


def test_undo_filing_refused_after_a_later_edit(client):
    capture = _capture(client, "Edited later")
    claim = client.post(f"/api/v1/captures/{capture['id']}/claim", json={"expected_generation": 1, "lease_seconds": 300}).json()
    filed = client.post(
        f"/api/v1/captures/{capture['id']}/interpretations",
        json={
            "expected_version": _current_version(client, capture["id"]),
            "expected_generation": 1,
            "mode": "processor",
            "lease_token": claim["lease_token"],
            "items": [{"kind": "create", "item": {"item_type": "note", "title": "Will be edited"}, "intent": "note", "confidence": "low"}],
        },
    ).json()
    note = filed["items"][0]
    edited = client.patch(f"/api/v1/items/{note['id']}", json={"expected_version": note["version"], "title": "Edited by hand"})
    assert edited.status_code == 200, edited.text
    undo = client.post(f"/api/v1/captures/{capture['id']}/undo-filing", json={"expected_version": filed["capture"]["version"]})
    assert undo.status_code == 409
    assert undo.json()["error"]["code"] == "version_conflict"
    assert client.get(f"/api/v1/items/{note['id']}").json()["archived_at"] is None


def test_log_steps_only_on_general_captures(client):
    response = client.post("/api/v1/captures", json={"source_type": "typed", "raw_text": "Buy milk", "metadata": {"processing_profile": "task_quick_add"}})
    assert response.status_code == 201, response.text
    capture = response.json()
    rejected = client.post(
        f"/api/v1/captures/{capture['id']}/interpretations",
        json={"expected_version": capture["version"], "expected_generation": 1, "items": [{"kind": "log", "text": "nope"}]},
    )
    assert rejected.status_code == 422


# --- runner ---------------------------------------------------------------------


class _Rest:
    def __init__(self):
        self.submitted = []

    def claim_next(self, *, lease_seconds):
        return {"capture_id": "c1", "generation": 1, "lease_token": str(uuid.uuid4()), "lease_expires_at": "2999-01-01T00:00:00+00:00"}

    def get_capture(self, capture_id):
        return {"id": capture_id, "version": 2, "source_type": "typed", "raw_text": "Went for a run", "metadata": {}, **CAPTURE}

    def list_categories(self):
        return []

    def list_projects(self):
        return []

    def list_folders(self):
        return []

    def list_locations(self):
        return LOCATIONS

    def submit_interpretation(self, capture_id, **kwargs):
        self.submitted.append(kwargs)
        return {}


def test_runner_files_general_typed_capture_through_the_planner(monkeypatch):
    import processor.runner as runner_module
    from processor.runner import RunnerConfig, run_once

    monkeypatch.setattr(planner, "_call_ollama", lambda m, s: json.dumps({"pieces": [piece("log", "Run", content_md="Went for a run")]}))
    rest = _Rest()
    result = run_once(rest=rest, config=RunnerConfig(api_token="t"), processor_settings=_settings(auto_file=True))
    assert result == {"capture_id": "c1", "status": "interpreted", "item_count": 1}
    [submitted] = rest.submitted
    assert submitted["operations"][0]["kind"] == "log"
    assert runner_module.extract_pieces is planner.extract_pieces
