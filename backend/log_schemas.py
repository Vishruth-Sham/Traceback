import uuid
import datetime as dt
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class LogEntryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=2000)
    at: datetime | None = None

    @field_validator("text")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must not be blank")
        return value


class LogEntryOut(BaseModel):
    id: uuid.UUID
    logged_at: datetime
    log_date: date
    text: str
    origin: Literal["ui", "mcp"]
    labels: list[str] = []


class LogDayOut(BaseModel):
    log_date: date
    summary: str | None = None
    entries: list[LogEntryOut]


class LogDaysOut(BaseModel):
    today: date
    days: list[LogDayOut]
    next_before: date | None = None


class LogRangeOut(BaseModel):
    start: date
    end: date
    days: list[LogDayOut]


class LogSearchOut(BaseModel):
    entries: list[LogEntryOut]


class LogCategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40)
    description: str = Field(default="", max_length=200)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip().lower()
        if not value:
            raise ValueError("name must not be blank")
        return value


class LogCategoryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=40)
    description: str | None = Field(default=None, max_length=200)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        if not value:
            raise ValueError("name must not be blank")
        return value


class LogCategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str


class ClassifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: dt.date | None = None
    all_days: bool = False
    # Scheduled catch-up: only days that have entries but no summary yet (see backend.log.classify).
    pending_only: bool = False

    @model_validator(mode="after")
    def pending_is_exclusive(self) -> "ClassifyRequest":
        if self.pending_only and (self.all_days or self.date is not None):
            raise ValueError("pending_only cannot be combined with date or all_days")
        return self


class ClassifyOut(BaseModel):
    classified_days: list[date]
    failed_days: list[date]
