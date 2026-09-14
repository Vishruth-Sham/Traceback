"""Allow nested filesystem-style folders (item_type='folder'), reusing items/item_relations."""
from alembic import op

revision = "20260915_0004"
down_revision = "20260914_0003"
branch_labels = depends_on = None

OLD_TYPES = "'note','task','project','entity','reference'"
NEW_TYPES = "'note','task','project','folder','entity','reference'"


def upgrade():
    op.drop_constraint("ck_items_type", "items", type_="check")
    op.create_check_constraint("ck_items_type", "items", f"item_type IN ({NEW_TYPES})")


def downgrade():
    op.drop_constraint("ck_items_type", "items", type_="check")
    op.create_check_constraint("ck_items_type", "items", f"item_type IN ({OLD_TYPES})")
