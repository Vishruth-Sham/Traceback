import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (CheckConstraint("byte_size >= 0", name="ck_asset_size"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    storage_key: Mapped[str] = mapped_column(String(80), unique=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    extension: Mapped[str] = mapped_column(String(32))
    declared_mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    detected_mime_type: Mapped[str] = mapped_column(String(255))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timestamp_origin: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(default=1)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    upload_state: Mapped[str] = mapped_column(String(24), default="ready")
    cleanup_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class CaptureAsset(Base):
    __tablename__ = "capture_assets"
    capture_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("captures.id", ondelete="CASCADE"), primary_key=True)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), primary_key=True)


class ItemAsset(Base):
    __tablename__ = "item_assets"
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), primary_key=True)
