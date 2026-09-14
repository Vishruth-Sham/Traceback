"""enforce one filesystem container per item

Revision ID: 20260915_0005
Revises: 20260915_0004
"""

from alembic import op


revision = "20260915_0005"
down_revision = "20260915_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Do not silently discard ambiguous user organization. If an older
    # database contains multiple parents, report the affected item IDs so the
    # user can resolve them before rerunning the migration.
    op.execute(
        """
        DO $$
        DECLARE duplicate_ids text;
        BEGIN
          SELECT string_agg(from_item_id::text, ', ' ORDER BY from_item_id::text)
            INTO duplicate_ids
            FROM (
              SELECT from_item_id
                FROM item_relations
               WHERE relation = 'part_of'
               GROUP BY from_item_id
              HAVING count(*) > 1
            ) duplicates;
          IF duplicate_ids IS NOT NULL THEN
            RAISE EXCEPTION 'Cannot enforce single-parent containment; resolve multiple part_of parents for item(s): %', duplicate_ids;
          END IF;
        END $$;
        """
    )
    op.create_index(
        "uq_item_relation_single_parent",
        "item_relations",
        ["from_item_id"],
        unique=True,
        postgresql_where="relation = 'part_of'",
    )


def downgrade() -> None:
    op.drop_index("uq_item_relation_single_parent", table_name="item_relations")
