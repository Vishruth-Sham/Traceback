"""Create Traceback core schema and fixed categories.

Revision ID: 20260914_0001
Revises:
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260914_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, unique=True),
    )
    op.bulk_insert(
        sa.table(
            "categories",
            sa.column("id", postgresql.UUID(as_uuid=True)),
            sa.column("slug", sa.String()),
            sa.column("name", sa.String()),
            sa.column("sort_order", sa.Integer()),
        ),
        [
            {"id": "0f29fa52-8ea8-5cd4-a473-d95710088821", "slug": "health-food", "name": "Health & Food", "sort_order": 10},
            {"id": "911ee164-c01e-56ac-83f3-ac979cedfb97", "slug": "personal-growth", "name": "Personal Growth", "sort_order": 20},
            {"id": "1bcf7a37-4a9e-5307-a2b0-99fc58d2a4f9", "slug": "books", "name": "Books", "sort_order": 30},
            {"id": "878a6f4a-cfca-539f-a38a-3a651dc2f214", "slug": "learning", "name": "Learning", "sort_order": 40},
            {"id": "7fdc3929-1555-5dec-9947-f5cd8b1651ca", "slug": "projects", "name": "Projects", "sort_order": 50},
            {"id": "88e4c4c7-36b5-57ed-889b-a68c50b226c9", "slug": "other", "name": "Other", "sort_order": 60},
        ],
    )
    op.create_table(
        "actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("actor", sa.String(32), nullable=False),
        sa.Column("client_label", sa.String(100), nullable=False),
        sa.Column("operation", sa.String(100), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=True),
        sa.Column("body_hash", sa.String(64), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("undone_by_action_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["undone_by_action_id"], ["actions.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("actor", "client_label", "operation", "idempotency_key", name="uq_action_idempotency"),
    )
    op.create_table(
        "items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("item_type", sa.String(24), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("placement_state", sa.String(16), nullable=False),
        sa.Column("attributes", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inbox_entered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_user_action_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("item_type IN ('note','task','project','entity','reference')", name="ck_items_type"),
        sa.CheckConstraint("placement_state IN ('inbox','classified')", name="ck_items_placement"),
        sa.CheckConstraint("(placement_state = 'inbox' AND category_id IS NULL) OR (placement_state = 'classified' AND category_id IS NOT NULL)", name="ck_items_placement_category"),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_items_item_type", "items", ["item_type"])
    op.create_index("ix_items_category_id", "items", ["category_id"])
    op.create_index("ix_items_placement_state", "items", ["placement_state"])
    op.create_index("ix_items_archived_at", "items", ["archived_at"])
    op.create_index("ix_items_active_updated", "items", ["archived_at", "updated_at", "id"])
    op.create_table(
        "task_details",
        sa.Column("item_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("due_time", sa.Time(timezone=False), nullable=True),
        sa.Column("due_timezone", sa.String(64), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('open','completed')", name="ck_task_status"),
        sa.CheckConstraint("(status = 'open' AND completed_at IS NULL) OR (status = 'completed' AND completed_at IS NOT NULL)", name="ck_task_completion"),
        sa.CheckConstraint("due_date IS NOT NULL OR (due_time IS NULL AND due_timezone IS NULL)", name="ck_task_due_parts"),
        sa.CheckConstraint("(due_time IS NULL AND due_timezone IS NULL) OR (due_time IS NOT NULL AND due_timezone IS NOT NULL)", name="ck_task_exact_deadline"),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_task_details_status", "task_details", ["status"])
    op.create_index("ix_task_details_due_date", "task_details", ["due_date"])
    op.create_table(
        "item_relations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("from_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation", sa.String(24), nullable=False),
        sa.Column("to_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("relation IN ('part_of','about','related_to')", name="ck_relation_type"),
        sa.CheckConstraint("from_item_id <> to_item_id", name="ck_relation_no_self"),
        sa.ForeignKeyConstraint(["from_item_id"], ["items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["to_item_id"], ["items.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("from_item_id", "relation", "to_item_id", name="uq_item_relation"),
    )
    op.create_index("ix_item_relations_from_item_id", "item_relations", ["from_item_id"])
    op.create_index("ix_item_relations_to_item_id", "item_relations", ["to_item_id"])
    op.create_table(
        "item_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resulting_version", sa.Integer(), nullable=False),
        sa.Column("before_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("after_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["action_id"], ["actions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("action_id", "item_id", name="uq_revision_action_item"),
    )
    op.create_index("ix_item_revisions_action_id", "item_revisions", ["action_id"])
    op.create_index("ix_item_revisions_item_id", "item_revisions", ["item_id"])
    op.create_index("ix_revision_item_created", "item_revisions", ["item_id", "created_at", "id"])

    op.execute(
        """
        CREATE FUNCTION enforce_task_detail_subtype() RETURNS trigger AS $$
        DECLARE checked_id uuid;
        DECLARE checked_ids uuid[];
        BEGIN
          IF TG_TABLE_NAME = 'items' THEN
            IF TG_OP = 'UPDATE' THEN
              checked_ids := ARRAY[OLD.id, NEW.id];
            ELSE
              checked_ids := ARRAY[NEW.id];
            END IF;
          ELSE
            IF TG_OP = 'DELETE' THEN
              checked_ids := ARRAY[OLD.item_id];
            ELSIF TG_OP = 'UPDATE' THEN
              checked_ids := ARRAY[OLD.item_id, NEW.item_id];
            ELSE
              checked_ids := ARRAY[NEW.item_id];
            END IF;
          END IF;
          FOREACH checked_id IN ARRAY checked_ids LOOP
            IF EXISTS (SELECT 1 FROM items WHERE id = checked_id AND item_type = 'task')
               AND NOT EXISTS (SELECT 1 FROM task_details WHERE item_id = checked_id) THEN
              RAISE EXCEPTION 'task item % requires task_details', checked_id USING ERRCODE = '23514';
            END IF;
            IF EXISTS (
              SELECT 1 FROM task_details td JOIN items i ON i.id = td.item_id
              WHERE td.item_id = checked_id AND i.item_type <> 'task'
            ) THEN
              RAISE EXCEPTION 'task_details % requires task item', checked_id USING ERRCODE = '23514';
            END IF;
          END LOOP;
          RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;

        CREATE CONSTRAINT TRIGGER items_task_detail_subtype
        AFTER INSERT OR UPDATE OF item_type ON items
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION enforce_task_detail_subtype();

        CREATE CONSTRAINT TRIGGER task_details_item_subtype
        AFTER INSERT OR UPDATE OF item_id OR DELETE ON task_details
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION enforce_task_detail_subtype();
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION enforce_task_detail_subtype() CASCADE")
    op.drop_table("item_revisions")
    op.drop_table("item_relations")
    op.drop_table("task_details")
    op.drop_table("items")
    op.drop_table("actions")
    op.drop_table("categories")
