"""Pure validation tests for the proposal envelope shape; no models required."""
import uuid

import pytest
from pydantic import ValidationError

from processor.schemas import ProposalEnvelope, ProposedItem


def test_accepts_minimal_note():
    envelope = ProposalEnvelope.model_validate({"items": [{"item_type": "note", "title": "Buy milk"}]})
    assert envelope.items[0].content_md == ""
    assert envelope.items[0].category_id is None


def test_rejects_more_than_ten_items():
    items = [{"item_type": "note", "title": f"n{i}"} for i in range(11)]
    with pytest.raises(ValidationError):
        ProposalEnvelope.model_validate({"items": items})


def test_rejects_deadline_on_non_task():
    with pytest.raises(ValidationError):
        ProposedItem.model_validate(
            {"item_type": "note", "title": "x", "due_date": "2026-09-15"}
        )


def test_rejects_blank_title():
    with pytest.raises(ValidationError):
        ProposedItem.model_validate({"item_type": "note", "title": "   "})


def test_rejects_due_time_without_timezone():
    with pytest.raises(ValidationError):
        ProposedItem.model_validate(
            {"item_type": "task", "title": "x", "due_date": "2026-09-15", "due_time": "17:00:00"}
        )


def test_rejects_nonexistent_local_time():
    # 2026-03-08 02:30 does not exist in America/Los_Angeles (spring-forward DST gap).
    with pytest.raises(ValidationError):
        ProposedItem.model_validate(
            {
                "item_type": "task",
                "title": "x",
                "due_date": "2026-03-08",
                "due_time": "02:30:00",
                "due_timezone": "America/Los_Angeles",
            }
        )


def test_accepts_valid_task_deadline():
    item = ProposedItem.model_validate(
        {
            "item_type": "task",
            "title": "Finish endpoint",
            "due_date": "2026-09-15",
            "due_time": "17:00:00",
            "due_timezone": "Asia/Kolkata",
        }
    )
    assert item.due_timezone == "Asia/Kolkata"


def test_accepts_uuid_category_id():
    cat = uuid.uuid4()
    item = ProposedItem.model_validate({"item_type": "note", "title": "x", "category_id": str(cat)})
    assert item.category_id == cat


def test_accepts_project_placement():
    project_id = uuid.uuid4()
    item = ProposedItem.model_validate({"item_type": "task", "title": "x", "project_id": str(project_id)})
    assert item.project_id == project_id
    assert item.folder_id is None


def test_accepts_folder_placement():
    folder_id = uuid.uuid4()
    item = ProposedItem.model_validate({"item_type": "note", "title": "x", "folder_id": str(folder_id)})
    assert item.folder_id == folder_id


def test_rejects_both_project_and_folder():
    with pytest.raises(ValidationError):
        ProposedItem.model_validate(
            {"item_type": "task", "title": "x", "project_id": str(uuid.uuid4()), "folder_id": str(uuid.uuid4())}
        )


def test_category_id_is_dropped_when_project_id_also_set():
    # category is derived from the container on the backend; a model that fills in both
    # should not fail validation over a field it shouldn't have set in the first place.
    item = ProposedItem.model_validate(
        {"item_type": "task", "title": "x", "category_id": str(uuid.uuid4()), "project_id": str(uuid.uuid4())}
    )
    assert item.category_id is None
    assert item.project_id is not None


def test_extra_keys_are_ignored_not_fatal():
    # Small local models sometimes emit extra keys despite prompt instructions;
    # the adapter tolerates them rather than failing the whole proposal.
    envelope = ProposalEnvelope.model_validate(
        {"items": [{"item_type": "note", "title": "x", "id": None, "status": "draft"}], "unexpected": True}
    )
    assert envelope.items[0].title == "x"
