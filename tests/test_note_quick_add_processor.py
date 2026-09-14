import json

import pytest

from processor.errors import InterpretationError
from processor.interpretation import interpret_note_location


def context():
    return {
        "supplied_title": "Keep this title",
        "placement_hint": "under reading",
        "locations": [
            {"kind": "folder", "id": "11111111-1111-1111-1111-111111111111", "title": "Reading", "path": "Learning / Reading", "version": 4},
            {"kind": "folder", "id": "22222222-2222-2222-2222-222222222222", "title": "Reading", "path": "Other / Reading", "version": 2},
        ],
    }


def test_note_proposal_preserves_supplied_title_and_uses_catalog_version(monkeypatch):
    monkeypatch.setattr(
        "processor.interpretation._call_ollama",
        lambda *_args, **_kwargs: json.dumps({"title": "Rewritten", "destination_kind": "folder", "destination_id": "11111111-1111-1111-1111-111111111111", "explanation": "The hint matches the Learning breadcrumb.", "confidence": "high"}),
    )
    result = interpret_note_location("Exact body", context())
    assert result["title"] == "Keep this title"
    assert result["destination_version"] == 4
    assert "content" not in result


def test_note_proposal_rejects_extra_fields_and_hallucinated_ids(monkeypatch):
    responses = iter([
        json.dumps({"title": "T", "destination_kind": None, "destination_id": None, "explanation": "Inbox", "content_md": "rewrite"}),
        json.dumps({"title": "T", "destination_kind": "folder", "destination_id": "33333333-3333-3333-3333-333333333333", "explanation": "invented", "confidence": "low"}),
    ])
    monkeypatch.setattr("processor.interpretation._call_ollama", lambda *_args, **_kwargs: next(responses))
    with pytest.raises(InterpretationError):
        interpret_note_location("Exact body", context())
