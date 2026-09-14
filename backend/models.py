import uuid
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, Time, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base


CATEGORY_IDS = {
    "health-food": uuid.UUID("0f29fa52-8ea8-5cd4-a473-d95710088821"),
    "personal-growth": uuid.UUID("911ee164-c01e-56ac-83f3-ac979cedfb97"),
    "books": uuid.UUID("1bcf7a37-4a9e-5307-a2b0-99fc58d2a4f9"),
    "learning": uuid.UUID("878a6f4a-cfca-539f-a38a-3a651dc2f214"),
    "projects": uuid.UUID("7fdc3929-1555-5dec-9947-f5cd8b1651ca"),
    "other": uuid.UUID("88e4c4c7-36b5-57ed-889b-a68c50b226c9"),
}


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    sort_order: Mapped[int] = mapped_column(Integer, unique=True)


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (
        CheckConstraint("item_type IN ('note','task','project','folder','entity','reference')", name="ck_items_type"),
        CheckConstraint("placement_state IN ('inbox','classified')", name="ck_items_placement"),
        CheckConstraint(
            "(placement_state = 'inbox' AND category_id IS NULL) OR "
            "(placement_state = 'classified' AND category_id IS NOT NULL)",
            name="ck_items_placement_category",
        ),
        Index("ix_items_active_updated", "archived_at", "updated_at", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_type: Mapped[str] = mapped_column(String(24), index=True)
    title: Mapped[str] = mapped_column(String(500))
    content_md: Mapped[str] = mapped_column(Text, default="")
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"), nullable=True, index=True)
    placement_state: Mapped[str] = mapped_column(String(16), index=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    inbox_entered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_user_action_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    category: Mapped[Category | None] = relationship(lazy="joined")
    task: Mapped["TaskDetail | None"] = relationship(back_populates="item", cascade="all, delete-orphan", uselist=False)


class TaskDetail(Base):
    __tablename__ = "task_details"
    __table_args__ = (
        CheckConstraint("status IN ('open','completed')", name="ck_task_status"),
        CheckConstraint("(status = 'open' AND completed_at IS NULL) OR (status = 'completed' AND completed_at IS NOT NULL)", name="ck_task_completion"),
        CheckConstraint("due_date IS NOT NULL OR (due_time IS NULL AND due_timezone IS NULL)", name="ck_task_due_parts"),
        CheckConstraint("(due_time IS NULL AND due_timezone IS NULL) OR (due_time IS NOT NULL AND due_timezone IS NOT NULL)", name="ck_task_exact_deadline"),
    )
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    due_time: Mapped[time | None] = mapped_column(Time(timezone=False), nullable=True)
    due_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    item: Mapped[Item] = relationship(back_populates="task")


class ItemRelation(Base):
    __tablename__ = "item_relations"
    __table_args__ = (
        CheckConstraint("relation IN ('part_of','about','related_to')", name="ck_relation_type"),
        CheckConstraint("from_item_id <> to_item_id", name="ck_relation_no_self"),
        UniqueConstraint("from_item_id", "relation", "to_item_id", name="uq_item_relation"),
        Index(
            "uq_item_relation_single_parent",
            "from_item_id",
            unique=True,
            postgresql_where=text("relation = 'part_of'"),
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="RESTRICT"), index=True)
    relation: Mapped[str] = mapped_column(String(24))
    to_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="RESTRICT"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Action(Base):
    __tablename__ = "actions"
    __table_args__ = (UniqueConstraint("actor", "client_label", "operation", "idempotency_key", name="uq_action_idempotency"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor: Mapped[str] = mapped_column(String(32), default="user")
    client_label: Mapped[str] = mapped_column(String(100), default="rest")
    operation: Mapped[str] = mapped_column(String(100))
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    body_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    undone_by_action_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("actions.id", ondelete="SET NULL"), nullable=True)


class ItemRevision(Base):
    __tablename__ = "item_revisions"
    __table_args__ = (UniqueConstraint("action_id", "item_id", name="uq_revision_action_item"), Index("ix_revision_item_created", "item_id", "created_at", "id"))
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    action_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actions.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    resulting_version: Mapped[int] = mapped_column(Integer)
    before_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
