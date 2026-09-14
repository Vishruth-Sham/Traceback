"""Add immutable captures, processing state, provenance, and corrections.

Revision ID: 20260914_0002
Revises: 20260914_0001
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260914_0002"
down_revision: str | None = "20260914_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "captures",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("original_description", sa.Text(), nullable=True),
        sa.Column("original_url", sa.String(8192), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_date", sa.Date(), nullable=True),
        sa.Column("source_timezone", sa.String(64), nullable=True),
        sa.Column("timestamp_origin", sa.String(24), nullable=False),
        sa.Column("source_metadata", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("source_type IN ('typed','audio','file','url','import')", name="ck_capture_source_type"),
        sa.CheckConstraint("timestamp_origin IN ('user_supplied','client_supplied','source_metadata','unknown')", name="ck_capture_timestamp_origin"),
    )
    op.create_index("ix_captures_archived_at", "captures", ["archived_at"])
    op.create_index("ix_captures_archive_created", "captures", ["archived_at", "created_at", "id"])
    op.create_table(
        "capture_processing",
        sa.Column("capture_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True, unique=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("state IN ('pending','processing','failed','resolved')", name="ck_capture_processing_state"),
        sa.CheckConstraint("generation >= 1", name="ck_capture_processing_generation"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_capture_processing_attempts"),
        sa.CheckConstraint("(state = 'processing' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR (state <> 'processing' AND lease_token IS NULL AND lease_expires_at IS NULL)", name="ck_capture_processing_lease"),
        sa.ForeignKeyConstraint(["capture_id"], ["captures.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_capture_processing_state", "capture_processing", ["state"])
    op.create_table(
        "item_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capture_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("link_kind", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["capture_id"], ["captures.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["action_id"], ["actions.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("item_id", "capture_id", name="uq_item_source"),
    )
    op.create_index("ix_item_sources_item_id", "item_sources", ["item_id"])
    op.create_index("ix_item_sources_capture_id", "item_sources", ["capture_id"])
    op.create_index("ix_item_sources_capture", "item_sources", ["capture_id", "item_id"])
    op.create_table(
        "capture_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("capture_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resulting_version", sa.Integer(), nullable=False),
        sa.Column("change_type", sa.String(40), nullable=False),
        sa.Column("changes", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["capture_id"], ["captures.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["action_id"], ["actions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("capture_id", "resulting_version", name="uq_capture_revision_version"),
    )
    op.create_index("ix_capture_revisions_capture_id", "capture_revisions", ["capture_id"])
    op.create_index("ix_capture_revisions_action_id", "capture_revisions", ["action_id"])
    op.create_index("ix_capture_revision_created", "capture_revisions", ["capture_id", "created_at", "id"])


def downgrade() -> None:
    op.drop_table("capture_revisions")
    op.drop_table("item_sources")
    op.drop_table("capture_processing")
    op.drop_table("captures")
