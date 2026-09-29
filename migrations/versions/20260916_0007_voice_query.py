"""Add durable read-only voice query results.

Revision ID: 20260916_0007
Revises: 20260915_0006
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260916_0007"
down_revision: str | None = "20260915_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("capture_processing", sa.Column("query_result", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("capture_processing", "query_result")
