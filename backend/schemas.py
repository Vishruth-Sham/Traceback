import uuid
from datetime import date, datetime, time
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ItemType = Literal["note", "task", "project", "folder"]
RelationType = Literal["part_of", "about", "related_to"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskFields(StrictModel):
    due_date: date | None = None
    due_time: time | None = None
    due_timezone: str | None = None

    @model_validator(mode="after")
    def validate_due_parts(self):
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
                local.replace(tzinfo=zone, fold=fold).astimezone(ZoneInfo("UTC")).astimezone(zone).replace(tzinfo=None) == local
                for fold in (0, 1)
            )
            if not valid:
                raise ValueError("due_time does not exist in due_timezone on due_date")
        return self


class ItemCreate(TaskFields):
    item_type: ItemType
    title: str = Field(min_length=1, max_length=500)
    content_md: str = ""
    category_id: uuid.UUID | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_type_fields(self):
        if self.item_type != "task" and any((self.due_date, self.due_time, self.due_timezone)):
            raise ValueError("deadline fields are only valid for tasks")
        if self.attributes:
            raise ValueError("attributes are reserved for validated item types in a later milestone")
        return self


class ItemCreateRequest(ItemCreate):
    project_id: uuid.UUID | None = None
    project_expected_version: int | None = Field(default=None, ge=1)
    folder_id: uuid.UUID | None = None
    folder_expected_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_container(self):
        if self.project_id is not None and self.folder_id is not None:
            raise ValueError("choose at most one of project_id or folder_id")
        if self.project_id is not None and self.project_expected_version is None:
            raise ValueError("project_expected_version is required when project_id is set")
        if self.folder_id is not None and self.folder_expected_version is None:
            raise ValueError("folder_expected_version is required when folder_id is set")
        if (self.project_id is not None or self.folder_id is not None) and self.category_id is not None:
            raise ValueError("category_id is derived from project_id/folder_id and must be omitted when either is set")
        return self


class ItemPatch(StrictModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    content_md: str | None = None
    category_id: uuid.UUID | None = None
    attributes: dict[str, Any] | None = None
    due_date: date | None = None
    due_time: time | None = None
    due_timezone: str | None = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("title cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_supplied_deadline(self):
        supplied = self.model_fields_set
        if "due_time" in supplied and self.due_time is not None and self.due_time.tzinfo is not None:
            raise ValueError("due_time must be a local wall time without an offset")
        if "due_timezone" in supplied and self.due_timezone is not None:
            try:
                ZoneInfo(self.due_timezone)
            except ZoneInfoNotFoundError as exc:
                raise ValueError("due_timezone must be an IANA timezone") from exc
        if "attributes" in supplied and self.attributes:
            raise ValueError("attributes are reserved for validated item types in a later milestone")
        return self


class AppendRequest(StrictModel):
    expected_version: int = Field(ge=1)
    content_md: str = Field(min_length=1)


class MoveRequest(StrictModel):
    expected_version: int = Field(ge=1)
    category_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    project_expected_version: int | None = Field(default=None, ge=1)
    folder_id: uuid.UUID | None = None
    folder_expected_version: int | None = Field(default=None, ge=1)
    inbox: bool = False

    @model_validator(mode="after")
    def one_destination(self):
        choices = int(self.category_id is not None) + int(self.project_id is not None) + int(self.folder_id is not None) + int(self.inbox)
        if choices != 1:
            raise ValueError("choose exactly one of category_id, project_id, folder_id, or inbox")
        if self.project_id is not None and self.project_expected_version is None:
            raise ValueError("project_expected_version is required for a project move")
        if self.folder_id is not None and self.folder_expected_version is None:
            raise ValueError("folder_expected_version is required for a folder move")
        return self


class VersionRequest(StrictModel):
    expected_version: int = Field(ge=1)


class RelationCreate(StrictModel):
    from_item_id: uuid.UUID
    from_expected_version: int = Field(ge=1)
    relation: RelationType
    to_item_id: uuid.UUID
    to_expected_version: int = Field(ge=1)


class RelationDelete(StrictModel):
    from_expected_version: int = Field(ge=1)
    to_expected_version: int = Field(ge=1)


class UndoRequest(StrictModel):
    expected_versions: dict[uuid.UUID, int]


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    slug: str
    name: str
    sort_order: int


class RelationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    from_item_id: uuid.UUID
    relation: str
    to_item_id: uuid.UUID
    created_at: datetime


class RelationMutationOut(RelationOut):
    action_id: uuid.UUID


class ItemOut(BaseModel):
    id: uuid.UUID
    item_type: str
    title: str
    content_md: str
    category_id: uuid.UUID | None
    placement_state: str
    attributes: dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    inbox_entered_at: datetime | None
    last_user_action_at: datetime
    status: str | None = None
    due_date: date | None = None
    due_time: time | None = None
    due_timezone: str | None = None
    completed_at: datetime | None = None
    overdue: bool | None = None
    relations: list[RelationOut] = Field(default_factory=list)
    action_id: uuid.UUID | None = None
    source_ids: list[uuid.UUID] = Field(default_factory=list)
    asset_ids: list[uuid.UUID] = Field(default_factory=list)


class ActionOut(BaseModel):
    id: uuid.UUID
    operation: str
    created_at: datetime
    undone_by_action_id: uuid.UUID | None


class RevisionOut(BaseModel):
    id: uuid.UUID
    action_id: uuid.UUID
    resulting_version: int
    before_snapshot: dict[str, Any] | None
    after_snapshot: dict[str, Any] | None
    created_at: datetime
