"""Local asset metadata and reference-aware links."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "20260914_0003"
down_revision = "20260914_0002"
branch_labels = depends_on = None


def upgrade():
    op.create_table("assets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("storage_key", sa.String(80), nullable=False, unique=True),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("extension", sa.String(32), nullable=False),
        sa.Column("declared_mime_type", sa.String(255)),
        sa.Column("detected_mime_type", sa.String(255), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("source_created_at", sa.DateTime(timezone=True)),
        sa.Column("source_modified_at", sa.DateTime(timezone=True)),
        sa.Column("timestamp_origin", sa.String(64)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("upload_state", sa.String(24), nullable=False),
        sa.Column("cleanup_error", sa.Text()),
        sa.CheckConstraint("byte_size >= 0", name="ck_asset_size"),
    )
    for table, owner, target in (("capture_assets", "capture_id", "captures"), ("item_assets", "item_id", "items")):
        op.create_table(table,
            sa.Column(owner, UUID(as_uuid=True), sa.ForeignKey(f"{target}.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("asset_id", UUID(as_uuid=True), sa.ForeignKey("assets.id", ondelete="RESTRICT"), primary_key=True),
        )


def downgrade():
    op.drop_table("item_assets")
    op.drop_table("capture_assets")
    op.drop_table("assets")
