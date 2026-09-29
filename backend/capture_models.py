import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base


class Capture(Base):
    __tablename__ = "captures"
    __table_args__ = (
        CheckConstraint("source_type IN ('typed','audio','file','url','import')", name="ck_capture_source_type"),
        CheckConstraint("timestamp_origin IN ('user_supplied','client_supplied','source_metadata','unknown')", name="ck_capture_timestamp_origin"),
        Index("ix_captures_archive_created", "archived_at", "created_at", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_type: Mapped[str] = mapped_column(String(20))
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_url: Mapped[str | None] = mapped_column(String(8192), nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timestamp_origin: Mapped[str] = mapped_column(String(24), default="unknown")
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    processing: Mapped["CaptureProcessing"] = relationship(back_populates="capture", cascade="all, delete-orphan", uselist=False)


class CaptureProcessing(Base):
    __tablename__ = "capture_processing"
    __table_args__ = (
        CheckConstraint("state IN ('pending','processing','awaiting_review','failed','resolved')", name="ck_capture_processing_state"),
        CheckConstraint("generation >= 1", name="ck_capture_processing_generation"),
        CheckConstraint("attempt_count >= 0", name="ck_capture_processing_attempts"),
        CheckConstraint(
            "(state = 'processing' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
            "(state <> 'processing' AND lease_token IS NULL AND lease_expires_at IS NULL)",
            name="ck_capture_processing_lease",
        ),
    )
    capture_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("captures.id", ondelete="CASCADE"), primary_key=True)
    generation: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposal: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    proposed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    query_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, unique=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    capture: Mapped[Capture] = relationship(back_populates="processing")


class ItemSource(Base):
    __tablename__ = "item_sources"
    __table_args__ = (
        UniqueConstraint("item_id", "capture_id", name="uq_item_source"),
        Index("ix_item_sources_capture", "capture_id", "item_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    capture_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("captures.id", ondelete="RESTRICT"), index=True)
    action_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("actions.id", ondelete="SET NULL"), nullable=True)
    link_kind: Mapped[str] = mapped_column(String(20), default="source")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CaptureRevision(Base):
    __tablename__ = "capture_revisions"
    __table_args__ = (
        UniqueConstraint("capture_id", "resulting_version", name="uq_capture_revision_version"),
        Index("ix_capture_revision_created", "capture_id", "created_at", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    capture_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("captures.id", ondelete="CASCADE"), index=True)
    action_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actions.id", ondelete="CASCADE"), index=True)
    resulting_version: Mapped[int] = mapped_column(Integer)
    change_type: Mapped[str] = mapped_column(String(40))
    changes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
