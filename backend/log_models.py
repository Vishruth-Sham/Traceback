import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base


class LogEntry(Base):
    """One free-text line of the daily log. Append-only; the text is never rewritten."""

    __tablename__ = "log_entries"
    __table_args__ = (
        CheckConstraint("origin IN ('ui','mcp')", name="ck_log_entry_origin"),
        CheckConstraint("length(btrim(text)) > 0", name="ck_log_entry_text"),
        Index("ix_log_entries_day", "log_date", "logged_at", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    log_date: Mapped[date] = mapped_column(Date)
    text: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LogCategory(Base):
    """An editable label the local model may apply. The description is what the model sees."""

    __tablename__ = "log_categories"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[str] = mapped_column(String(200), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class EntryLabel(Base):
    """Derived and disposable: rebuilt by the classifier, never a source of truth."""

    __tablename__ = "entry_labels"
    entry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("log_entries.id", ondelete="CASCADE"), primary_key=True)
    label: Mapped[str] = mapped_column(String(40), primary_key=True)
    model: Mapped[str] = mapped_column(String(100))


class DaySummary(Base):
    """Derived and disposable: rebuilt by the classifier."""

    __tablename__ = "day_summaries"
    log_date: Mapped[date] = mapped_column(Date, primary_key=True)
    summary: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
