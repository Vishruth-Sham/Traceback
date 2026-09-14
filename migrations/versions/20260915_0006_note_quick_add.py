"""Add durable reviewed proposals for note quick add.

Revision ID: 20260915_0006
Revises: 20260915_0005
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260915_0006"
down_revision: str | None = "20260915_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_capture_processing_state", "capture_processing", type_="check")
    op.create_check_constraint(
        "ck_capture_processing_state",
        "capture_processing",
        "state IN ('pending','processing','awaiting_review','failed','resolved')",
    )
    op.add_column("capture_processing", sa.Column("proposal", postgresql.JSONB(), nullable=True))
    op.add_column("capture_processing", sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("capture_processing", "proposed_at")
    op.drop_column("capture_processing", "proposal")
    op.drop_constraint("ck_capture_processing_state", "capture_processing", type_="check")
    op.create_check_constraint(
        "ck_capture_processing_state", "capture_processing", "state IN ('pending','processing','failed','resolved')"
    )
