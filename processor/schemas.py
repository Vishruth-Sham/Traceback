"""Validated shape of the proposal envelope returned by `interpret`.

Mirrors the deadline rules enforced by `backend/schemas.py` (TaskFields) so a
malformed model output is rejected here rather than at the backend, without
importing backend modules from this worker's own files.
"""

import uuid
from datetime import date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

ItemType = Literal["note", "task", "project"]


class ProposedItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    item_type: ItemType
    title: str = Field(min_length=1, max_length=500)
    content_md: str = ""
    category_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    folder_id: uuid.UUID | None = None
    due_date: date | None = None
    due_time: time | None = None
    due_timezone: str | None = None

    @model_validator(mode="after")
    def validate_fields(self):
        if not self.title.strip():
            raise ValueError("title cannot be blank")
        if self.project_id is not None and self.folder_id is not None:
            raise ValueError("choose at most one of project_id or folder_id")
        if (self.project_id is not None or self.folder_id is not None) and self.category_id is not None:
            # category is derived from the container on the backend; drop the
            # redundant/possibly-contradictory value rather than reject the
            # whole proposal for a field the model shouldn't have filled in.
            self.category_id = None
        if self.item_type != "task" and any((self.due_date, self.due_time, self.due_timezone)):
            raise ValueError("deadline fields are only valid for tasks")
        if self.due_date is None and (self.due_time is not None or self.due_timezone is not None):
            raise ValueError("due_time and due_timezone require due_date")
        if self.due_time is not None and self.due_timezone is None:
            raise ValueError("due_timezone is required when due_time is set")
        if self.due_time is None and self.due_timezone is not None:
            raise ValueError("due_timezone is only stored for an exact due time")
        if self.due_timezone:
            try:
                ZoneInfo(self.due_timezone)
            except ZoneInfoNotFoundError as exc:
                raise ValueError("due_timezone must be an IANA timezone") from exc
        if self.due_time is not None and self.due_time.tzinfo is not None:
            raise ValueError("due_time must be a local wall time without an offset")
        if self.due_date and self.due_time and self.due_timezone:
            zone = ZoneInfo(self.due_timezone)
            local = datetime.combine(self.due_date, self.due_time)
            valid = any(
                local.replace(tzinfo=zone, fold=fold).astimezone(ZoneInfo("UTC")).astimezone(zone).replace(tzinfo=None)
                == local
                for fold in (0, 1)
            )
            if not valid:
                raise ValueError("due_time does not exist in due_timezone on due_date")
        return self


class ProposalEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[ProposedItem] = Field(max_length=10)


class NoteLocationProposal(BaseModel):
    """Strict model output for note quick add; deliberately contains no note body."""

    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=500)
    destination_kind: Literal["category", "project", "folder"] | None = None
    destination_id: uuid.UUID | None = None
    explanation: str = Field(min_length=1, max_length=1000)
    confidence: Literal["high", "medium", "low"] | None = None

    @model_validator(mode="after")
    def complete_destination(self):
        if (self.destination_kind is None) != (self.destination_id is None):
            raise ValueError("destination_kind and destination_id must be supplied together")
        return self
