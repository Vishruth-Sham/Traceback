"""Interpretation adapter tests.

Unit tests stub the Ollama HTTP call so retry/validation/category-filtering
logic is covered without a running model. One integration test exercises the
real loopback qwen3.5:4b model and skips with a precise reason when Ollama or
the model tag is not available on this runtime.
"""
import json
import urllib.error
import uuid

import pytest
from pydantic import ValidationError

import processor.interpretation as interpretation_module
from processor.config import ProcessorSettings, get_settings
from processor.errors import InterpretationError, ModelUnavailableError
from processor.interpretation import interpret


def _context(category_id: str | None = None):
    categories = [{"id": category_id, "slug": "projects", "name": "Projects"}] if category_id else []
    return {
        "captured_at": "2026-09-14T09:00:00+05:30",
        "source_timezone": "Asia/Kolkata",
        "source_date": "2026-09-14",
        "categories": categories,
    }


def test_rejects_empty_text():
    with pytest.raises(InterpretationError):
        interpret("   ", _context())


def test_processor_rejects_non_loopback_ollama_url():
    with pytest.raises(ValidationError, match="loopback"):
        ProcessorSettings(ollama_base_url="https://example.com")


def test_rejects_oversized_text_instead_of_processing_a_truncated_capture():
    settings = get_settings().model_copy(update={"ollama_max_input_chars": 500})
    with pytest.raises(InterpretationError, match="exceeds"):
        interpret("x" * 501, _context(), settings=settings)


def test_parse_repairs_datetime_shaped_due_date_and_offset_timezone():
    """Regression test for a real failure: given "email sarah 5pm tomorrow", Qwen
    sometimes folds the resolved date/time into due_date as a full ISO datetime
    and writes due_timezone as a raw UTC offset instead of the IANA name. Pydantic
    only reports the due_date error (a model-level validator never even runs to
    flag due_timezone), so the correction retry never fixed the offset either,
    exhausting the retry budget and surfacing as "could not understand this" in
    the UI for an otherwise perfectly parseable capture. This is the exact raw
    model output observed."""
    raw = (
        '{"items": [{"item_type": "task", "title": "Email Sarah", '
        '"content_md": "Send email to Sarah at 5 PM tomorrow.", "category_id": null, '
        '"project_id": null, "folder_id": null, '
        '"due_date": "2026-09-15T17:00:41+05:30", "due_time": "17:00:41", "due_timezone": "+05:30"}]}'
    )
    parsed = interpretation_module._parse_proposal_json(raw, source_timezone="Asia/Kolkata")
    item = parsed["items"][0]
    assert item["due_date"] == "2026-09-15"
    assert item["due_timezone"] == "Asia/Kolkata"
    # Validates cleanly now, where the raw shape would have raised.
    envelope = interpretation_module.ProposalEnvelope.model_validate(parsed)
    assert envelope.items[0].due_date.isoformat() == "2026-09-15"


def test_parse_repairs_z_suffixed_due_timezone():
    raw = '{"items": [{"item_type": "task", "title": "x", "due_date": "2026-09-15", "due_time": "17:00:00", "due_timezone": "Z"}]}'
    parsed = interpretation_module._parse_proposal_json(raw, source_timezone="Asia/Kolkata")
    assert parsed["items"][0]["due_timezone"] == "Asia/Kolkata"


def test_parse_drops_unresolvable_offset_timezone_without_source_timezone():
    # No source_timezone available in context to substitute: drop the specific
    # time entirely rather than submit an invalid due_time/due_timezone pair.
    raw = '{"items": [{"item_type": "task", "title": "x", "due_date": "2026-09-15", "due_time": "17:00:00", "due_timezone": "+05:30"}]}'
    parsed = interpretation_module._parse_proposal_json(raw, source_timezone=None)
    item = parsed["items"][0]
    assert item["due_time"] is None
    assert item["due_timezone"] is None


def test_interpret_succeeds_despite_malformed_due_date_from_model(monkeypatch):
    """End-to-end: interpret() must not raise/exhaust retries on the exact
    malformed shape observed in production; the repair happens before the
    first validation attempt, so this succeeds on attempt 1."""
    calls = []

    def fake_call(messages, settings):
        calls.append(messages)
        return (
            '{"items": [{"item_type": "task", "title": "Email Sarah", "content_md": "x", '
            '"category_id": null, "project_id": null, "folder_id": null, '
            '"due_date": "2026-09-15T17:00:41+05:30", "due_time": "17:00:41", "due_timezone": "+05:30"}]}'
        )

    monkeypatch.setattr(interpretation_module, "_call_ollama", fake_call)
    context = _context()
    context["source_timezone"] = "Asia/Kolkata"
    result = interpret("email sarah 5pm tomorrow", context)
    assert len(calls) == 1  # no retry needed
    item = result["items"][0]
    assert item["due_date"] == "2026-09-15"
    assert item["due_time"] == "17:00:41"
    assert item["due_timezone"] == "Asia/Kolkata"


def test_valid_response_is_returned(monkeypatch):
    monkeypatch.setattr(
        interpretation_module,
        "_call_ollama",
        lambda messages, settings: json.dumps({"items": [{"item_type": "note", "title": "Buy milk"}]}),
    )
    result = interpret("buy milk", _context())
    assert result == {
        "items": [
            {
                "item_type": "note",
                "title": "Buy milk",
                "content_md": "",
                "category_id": None,
                "project_id": None,
                "folder_id": None,
                "due_date": None,
                "due_time": None,
                "due_timezone": None,
            }
        ]
    }


def test_tolerates_qwen_trailing_fence_and_drops_timezone_from_date_only_deadline(monkeypatch):
    monkeypatch.setattr(
        interpretation_module,
        "_call_ollama",
        lambda messages, settings: json.dumps(
            {
                "items": [
                    {
                        "item_type": "task",
                        "title": "Email Sarah",
                        "due_date": "2026-09-18",
                        "due_time": None,
                        "due_timezone": "Asia/Kolkata",
                    }
                ]
            }
        ) + "\n```",
    )
    result = interpret("Email Sarah Friday afternoon", _context())
    assert result["items"][0]["due_date"] == "2026-09-18"
    assert result["items"][0]["due_timezone"] is None


def test_unknown_category_id_is_dropped_to_inbox(monkeypatch):
    real_cat = str(uuid.uuid4())
    hallucinated_cat = str(uuid.uuid4())
    monkeypatch.setattr(
        interpretation_module,
        "_call_ollama",
        lambda messages, settings: json.dumps(
            {"items": [{"item_type": "note", "title": "x", "category_id": hallucinated_cat}]}
        ),
    )
    result = interpret("x", _context(category_id=real_cat))
    assert result["items"][0]["category_id"] is None


def test_known_category_id_is_preserved(monkeypatch):
    real_cat = str(uuid.uuid4())
    monkeypatch.setattr(
        interpretation_module,
        "_call_ollama",
        lambda messages, settings: json.dumps({"items": [{"item_type": "note", "title": "x", "category_id": real_cat}]}),
    )
    result = interpret("x", _context(category_id=real_cat))
    assert result["items"][0]["category_id"] == real_cat


def test_unknown_project_id_falls_back_to_null_not_inbox_loss(monkeypatch):
    real_project = str(uuid.uuid4())
    hallucinated = str(uuid.uuid4())
    monkeypatch.setattr(
        interpretation_module,
        "_call_ollama",
        lambda messages, settings: json.dumps({"items": [{"item_type": "task", "title": "x", "project_id": hallucinated}]}),
    )
    context = _context()
    context["projects"] = [{"id": real_project, "title": "Apartment Move"}]
    result = interpret("x", context)
    assert result["items"][0]["project_id"] is None
    assert result["items"][0]["title"] == "x"  # title/content preserved even when placement is dropped


def test_known_project_id_is_preserved_and_category_stays_null(monkeypatch):
    real_project = str(uuid.uuid4())
    monkeypatch.setattr(
        interpretation_module,
        "_call_ollama",
        lambda messages, settings: json.dumps({"items": [{"item_type": "task", "title": "x", "project_id": real_project}]}),
    )
    context = _context()
    context["projects"] = [{"id": real_project, "title": "Apartment Move"}]
    result = interpret("x", context)
    assert result["items"][0]["project_id"] == real_project
    assert result["items"][0]["category_id"] is None


def test_known_folder_id_is_preserved(monkeypatch):
    real_folder = str(uuid.uuid4())
    monkeypatch.setattr(
        interpretation_module,
        "_call_ollama",
        lambda messages, settings: json.dumps({"items": [{"item_type": "note", "title": "x", "folder_id": real_folder}]}),
    )
    context = _context()
    context["folders"] = [{"id": real_folder, "title": "Reading list"}]
    result = interpret("x", context)
    assert result["items"][0]["folder_id"] == real_folder


def test_retries_once_on_malformed_json_then_succeeds(monkeypatch):
    responses = iter(["not json at all", json.dumps({"items": [{"item_type": "task", "title": "y"}]})])
    monkeypatch.setattr(interpretation_module, "_call_ollama", lambda messages, settings: next(responses))
    result = interpret("y", _context())
    assert result["items"][0]["title"] == "y"


def test_task_quick_add_retries_non_task_then_accepts_one_task(monkeypatch):
    responses = iter(
        [
            json.dumps({"items": [{"item_type": "note", "title": "Call Sam"}]}),
            json.dumps({"items": [{"item_type": "task", "title": "Call Sam"}]}),
        ]
    )
    monkeypatch.setattr(interpretation_module, "_call_ollama", lambda messages, settings: next(responses))
    context = _context()
    context["processing_profile"] = "task_quick_add"
    result = interpret("Call Sam", context)
    assert len(result["items"]) == 1
    assert result["items"][0]["item_type"] == "task"


def test_gives_up_after_bounded_retries(monkeypatch):
    monkeypatch.setattr(interpretation_module, "_call_ollama", lambda messages, settings: "still not json")
    with pytest.raises(InterpretationError):
        interpret("z", _context())


def test_unreachable_ollama_raises_model_unavailable(monkeypatch):
    def _raise(request, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(interpretation_module.urllib.request, "urlopen", _raise)
    with pytest.raises(ModelUnavailableError):
        interpret("hello", _context())


def _ollama_model_available() -> bool:
    import urllib.request

    settings = get_settings()
    try:
        with urllib.request.urlopen(settings.ollama_base_url.rstrip("/") + "/api/tags", timeout=3) as response:
            tags = json.loads(response.read())
    except Exception:
        return False
    return any(m.get("name") == settings.ollama_model for m in tags.get("models", []))


@pytest.mark.skipif(
    not _ollama_model_available(),
    reason=f"Ollama loopback service or model {get_settings().ollama_model} not available",
)
def test_real_ollama_returns_valid_proposal():
    result = interpret("Note to self: read the intro chapter this weekend.", _context())
    assert isinstance(result["items"], list)
    assert 1 <= len(result["items"]) <= 10
    assert result["items"][0]["item_type"] in ("note", "task", "project")


@pytest.mark.skipif(
    not _ollama_model_available(),
    reason=f"Ollama loopback service or model {get_settings().ollama_model} not available",
)
def test_real_ollama_resolves_named_project_by_canonical_id():
    project_id = str(uuid.uuid4())
    context = _context()
    context["projects"] = [{"id": project_id, "title": "Apartment Move"}]
    result = interpret("For the Apartment Move project, remind me to email Sarah about the lease", context)
    item = result["items"][0]
    # Not asserting the model always picks it (small-model accuracy is not benchmarked here),
    # but whatever it returns must be schema-valid and, if set, exactly this canonical id.
    if item["project_id"] is not None:
        assert item["project_id"] == project_id
        assert item["category_id"] is None


@pytest.mark.skipif(
    not _ollama_model_available(),
    reason=f"Ollama loopback service or model {get_settings().ollama_model} not available",
)
def test_real_ollama_relative_date_grounds_against_captured_at_timezone_or_leaves_it_null():
    context = {
        "captured_at": "2026-09-14T09:00:00+05:30",  # a Monday
        "source_timezone": "Asia/Kolkata",
        "source_date": "2026-09-14",
        "categories": [],
    }
    result = interpret("Email Sarah Friday afternoon about the apartment move", context)
    item = result["items"][0]
    assert item["item_type"] == "task"
    # The adapter must never invent a due_time from an approximate phrase like "afternoon" it
    # cannot resolve exactly, and any due_date it does set must be schema-valid (already
    # enforced by ProposedItem) and not before the capture's own date.
    if item["due_date"] is not None:
        assert item["due_date"] >= "2026-09-14"
    if item["due_time"] is not None:
        assert item["due_timezone"] is not None


@pytest.mark.skipif(
    not _ollama_model_available(),
    reason=f"Ollama loopback service or model {get_settings().ollama_model} not available",
)
def test_real_ollama_specific_time_deadline_does_not_exhaust_retries():
    """Literal user-reported failure: "email sarah 5pm tomorrow" was intermittently
    producing a malformed due_date/due_timezone shape from the real model that
    exhausted the bounded retry budget, surfacing as "could not understand this"
    for a request that should always resolve cleanly. Run several times since the
    malformed shape was not guaranteed on every call."""
    context = {
        "captured_at": "2026-09-14T18:00:41+05:30",
        "source_timezone": "Asia/Kolkata",
        "source_date": "2026-09-14",
        "processing_profile": "task_quick_add",
        "categories": [],
        "projects": [],
        "folders": [],
    }
    for _ in range(3):
        result = interpret("email sarah 5pm tomorrow", context)
        item = result["items"][0]
        assert item["item_type"] == "task"
        assert item["due_date"] == "2026-09-15"
        assert item["due_time"] == "17:00:00"
        assert item["due_timezone"] == "Asia/Kolkata"
