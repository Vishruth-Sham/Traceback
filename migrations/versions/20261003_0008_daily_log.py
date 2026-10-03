"""Daily log: free-text entries plus disposable labels and summaries.

Revision ID: 20261003_0008
Revises: 20260916_0007
"""
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "20261003_0008"
down_revision = "20260916_0007"
branch_labels = depends_on = None

DEFAULT_CATEGORIES = [
    ("food", "Meals, snacks, drinks, cooking"),
    ("exercise", "Gym, runs, walks, sports"),
    ("work", "Job tasks, meetings, planning, admin"),
    ("reading", "Books, articles, study"),
    ("social", "Time with people, calls, events"),
    ("errands", "Chores, appointments, shopping"),
    ("health", "Sleep, symptoms, medication, rest"),
]


def upgrade():
    op.create_table("log_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("logged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("log_date", sa.Date(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("origin", sa.String(8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("origin IN ('ui','mcp')", name="ck_log_entry_origin"),
        sa.CheckConstraint("length(btrim(text)) > 0", name="ck_log_entry_text"),
    )
    op.create_index("ix_log_entries_day", "log_entries", ["log_date", "logged_at", "id"])
    categories = op.create_table("log_categories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(40), nullable=False, unique=True),
        sa.Column("description", sa.String(200), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.bulk_insert(categories, [
        {"id": uuid.uuid5(uuid.NAMESPACE_URL, f"traceback:log-category:{name}"), "name": name, "description": description, "sort_order": order}
        for order, (name, description) in enumerate(DEFAULT_CATEGORIES)
    ])
    op.create_table("entry_labels",
        sa.Column("entry_id", UUID(as_uuid=True), sa.ForeignKey("log_entries.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("label", sa.String(40), primary_key=True),
        sa.Column("model", sa.String(100), nullable=False),
    )
    op.create_table("day_summaries",
        sa.Column("log_date", sa.Date(), primary_key=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("day_summaries")
    op.drop_table("entry_labels")
    op.drop_table("log_categories")
    op.drop_index("ix_log_entries_day", table_name="log_entries")
    op.drop_table("log_entries")
