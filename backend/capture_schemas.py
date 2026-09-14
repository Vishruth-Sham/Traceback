import uuid
from datetime import date, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.schemas import ItemCreate, StrictModel


class CaptureMetadata(StrictModel):
    processing_profile: Literal["general", "task_quick_add", "note_quick_add"] = "general"
    client_app: str | None = Field(default=None, max_length=200)
    external_source_id: str | None = Field(default=None, max_length=500)
    contextual_item_id: uuid.UUID | None = None
    timestamp_precision: Literal["exact", "date", "approximate", "unknown"] = "unknown"
    supplied_title: str | None = Field(default=None, max_length=1000)
    supplied_author: str | None = Field(default=None, max_length=500)
    supplied_published_date: date | None = None
    placement_hint: str | None = Field(default=None, max_length=2000)


class CaptureCreate(StrictModel):
    source_type: Literal["typed", "audio", "file", "url", "import"]
    raw_text: str | None = Field(default=None, max_length=2_000_000)
    description: str | None = Field(default=None, max_length=20_000)
    url: AnyHttpUrl | None = None
    captured_at: datetime | None = None
    source_date: date | None = None
    source_timezone: str | None = None
    timestamp_origin: Literal["user_supplied", "client_supplied", "source_metadata", "unknown"] = "unknown"
    metadata: CaptureMetadata = Field(default_factory=CaptureMetadata)
    asset_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)

    @field_validator("captured_at")
    @classmethod
    def captured_at_is_aware(cls, value: datetime | None):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("captured_at must include a timezone offset")
        return value

    @field_validator("source_timezone")
    @classmethod
    def valid_timezone(cls, value: str | None):
        if value:
            try:
                ZoneInfo(value)
            except ZoneInfoNotFoundError as exc:
                raise ValueError("source_timezone must be an IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def validate_source(self):
        if len(set(self.asset_ids)) != len(self.asset_ids):
            raise ValueError("asset_ids must be unique")
        if self.source_type == "typed" and not (self.raw_text and self.raw_text.strip()):
            raise ValueError("typed captures require raw_text")
        if self.source_type == "url" and self.url is None:
            raise ValueError("url captures require url")
        if self.source_type in ("audio", "file") and not self.asset_ids:
            raise ValueError(f"{self.source_type} captures require at least one asset")
        if not any((self.raw_text, self.description, self.url, self.asset_ids)):
            raise ValueError("capture must preserve text, description, URL, or an asset")
        if (self.captured_at or self.source_date) and self.timestamp_origin == "unknown":
            raise ValueError("timestamp_origin is required when a source timestamp is supplied")
        return self


class CaptureCorrectionCreate(StrictModel):
    expected_version: int = Field(ge=1)
    description: str | None = Field(default=None, max_length=20_000)
    url: AnyHttpUrl | None = None
    captured_at: datetime | None = None
    source_date: date | None = None
    source_timezone: str | None = None
    note: str | None = Field(default=None, max_length=10_000)
    note_text: str | None = Field(default=None, min_length=1, max_length=2_000_000)
    supplied_title: str | None = Field(default=None, max_length=1000)
    placement_hint: str | None = Field(default=None, max_length=2000)

    @field_validator("captured_at")
    @classmethod
    def captured_at_is_aware(cls, value: datetime | None):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("captured_at must include a timezone offset")
        return value

    @field_validator("source_timezone")
    @classmethod
    def valid_timezone(cls, value: str | None):
        if value:
            try:
                ZoneInfo(value)
            except ZoneInfoNotFoundError as exc:
                raise ValueError("source_timezone must be an IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def has_correction(self):
        if not (self.model_fields_set - {"expected_version"}):
            raise ValueError("at least one correction field is required")
        return self


class CaptureVersionRequest(StrictModel):
    expected_version: int = Field(ge=1)


class CaptureRetryRequest(CaptureVersionRequest):
    expected_generation: int = Field(ge=1)


class CaptureClaimRequest(StrictModel):
    expected_generation: int = Field(ge=1)
    lease_seconds: int = Field(default=300, ge=30, le=900)


class CaptureFailRequest(StrictModel):
    expected_generation: int = Field(ge=1)
    lease_token: uuid.UUID
    error_code: str = Field(min_length=1, max_length=100)
    error_message: str = Field(min_length=1, max_length=10_000)
    transcript: str | None = Field(default=None, max_length=2_000_000)


class NoteProposal(StrictModel):
    title: str = Field(min_length=1, max_length=500)
    destination_kind: Literal["category", "project", "folder"] | None = None
    destination_id: uuid.UUID | None = None
    destination_version: int | None = Field(default=None, ge=1)
    explanation: str = Field(min_length=1, max_length=1000)
    confidence: Literal["high", "medium", "low"] | None = None

    @model_validator(mode="after")
    def destination_is_complete(self):
        values = (self.destination_kind, self.destination_id)
        if (values[0] is None) != (values[1] is None):
            raise ValueError("destination_kind and destination_id must be supplied together")
        if self.destination_kind in ("project", "folder") and self.destination_version is None:
            raise ValueError("versioned destinations require destination_version")
        if self.destination_kind == "category" and self.destination_version is not None:
            raise ValueError("categories are not versioned")
        return self


class CaptureProposalRequest(StrictModel):
    expected_version: int = Field(ge=1)
    expected_generation: int = Field(ge=1)
    lease_token: uuid.UUID
    proposal: NoteProposal


class CreateInterpretationItem(StrictModel):
    kind: Literal["create"] = "create"
    item: ItemCreate
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
        if (self.project_id is not None or self.folder_id is not None) and self.item.category_id is not None:
            raise ValueError("category_id is derived from project_id/folder_id and must be omitted when either is set")
        return self


class AppendInterpretationItem(StrictModel):
    kind: Literal["append"]
    item_id: uuid.UUID
    expected_version: int = Field(ge=1)
    content_md: str = Field(min_length=1, max_length=2_000_000)


InterpretationItem = Annotated[CreateInterpretationItem | AppendInterpretationItem, Field(discriminator="kind")]


class CaptureInterpretationRequest(StrictModel):
    expected_version: int = Field(ge=1)
    expected_generation: int = Field(ge=1)
    mode: Literal["manual", "processor"] = "manual"
    lease_token: uuid.UUID | None = None
    transcript: str | None = Field(default=None, max_length=2_000_000)
    items: list[InterpretationItem] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_mode(self):
        if self.mode == "processor" and self.lease_token is None:
            raise ValueError("processor interpretations require lease_token")
        if self.mode == "manual" and self.lease_token is not None:
            raise ValueError("manual interpretations cannot supply lease_token")
        existing_ids = [item.item_id for item in self.items if isinstance(item, AppendInterpretationItem)]
        if len(existing_ids) != len(set(existing_ids)):
            raise ValueError("an existing item may appear only once per interpretation")
        return self


class SourceLinkRequest(StrictModel):
    capture_id: uuid.UUID
    item_expected_version: int = Field(ge=1)
    capture_expected_version: int = Field(ge=1)


class SourceUnlinkRequest(StrictModel):
    item_expected_version: int = Field(ge=1)
    capture_expected_version: int = Field(ge=1)


class ProcessingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    generation: int
    state: str
    transcript: str | None
    proposal: dict | None
    proposed_at: datetime | None
    error_code: str | None
    error_message: str | None
    attempt_count: int
    lease_expires_at: datetime | None
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class CaptureOut(BaseModel):
    id: uuid.UUID
    source_type: str
    raw_text: str | None
    original_description: str | None
    original_url: str | None
    captured_at: datetime | None
    source_date: date | None
    source_timezone: str | None
    timestamp_origin: str
    metadata: dict
    corrections: dict
    asset_ids: list[uuid.UUID]
    resulting_item_ids: list[uuid.UUID]
    version: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    processing: ProcessingOut
    action_id: uuid.UUID | None = None


class CaptureRevisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    action_id: uuid.UUID
    resulting_version: int
    change_type: str
    changes: dict
    created_at: datetime


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    item_id: uuid.UUID
    capture_id: uuid.UUID
    action_id: uuid.UUID | None
    link_kind: str
    created_at: datetime


class ClaimOut(BaseModel):
    capture_id: uuid.UUID
    generation: int
    lease_token: uuid.UUID
    lease_expires_at: datetime
