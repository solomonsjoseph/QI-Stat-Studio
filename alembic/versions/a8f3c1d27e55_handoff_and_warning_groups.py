"""handoff columns on uploads and warning_groups table

Revision ID: a8f3c1d27e55
Revises: 7edd4ff961ce
Create Date: 2026-10-23 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a8f3c1d27e55"
down_revision: Union[str, Sequence[str], None] = "7edd4ff961ce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}
SOURCE_FK = "fk_uploads_handoff_source_upload_id_uploads"


def upgrade() -> None:
    with op.batch_alter_table("uploads", naming_convention=NAMING_CONVENTION) as batch:
        batch.add_column(sa.Column("handoff_md", sa.Text(), nullable=True))
        batch.add_column(sa.Column("handoff_steps", sa.Text(), server_default="[]", nullable=False))
        batch.add_column(sa.Column("handoff_revision", sa.Integer(), server_default="0", nullable=False))
        batch.add_column(sa.Column("handoff_revisions", sa.Text(), server_default="[]", nullable=False))
        batch.add_column(sa.Column("handoff_status", sa.String(20), server_default="none", nullable=False))
        batch.add_column(sa.Column("handoff_updated_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("handoff_replaced_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("handoff_source_upload_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("dictionary_checksum_sha256", sa.String(64), server_default="", nullable=False))
        batch.create_foreign_key(SOURCE_FK, "uploads", ["handoff_source_upload_id"], ["id"], ondelete="SET NULL")

    op.create_table(
        "warning_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("upload_id", sa.Integer(), sa.ForeignKey("uploads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("flag_ids", sa.Text(), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), server_default="open", nullable=False),
        sa.Column("advisor_turns", sa.Text(), server_default="[]", nullable=False),
        sa.Column("pending_proposal", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("handled_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_warning_groups_project_id", "warning_groups", ["project_id"])
    op.create_index("ix_warning_groups_upload_id", "warning_groups", ["upload_id"])


def downgrade() -> None:
    op.drop_index("ix_warning_groups_upload_id", table_name="warning_groups")
    op.drop_index("ix_warning_groups_project_id", table_name="warning_groups")
    op.drop_table("warning_groups")

    with op.batch_alter_table("uploads", naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_constraint(SOURCE_FK, type_="foreignkey")
        for col in (
            "dictionary_checksum_sha256", "handoff_source_upload_id", "handoff_replaced_at",
            "handoff_updated_at", "handoff_status", "handoff_revisions", "handoff_revision",
            "handoff_steps", "handoff_md",
        ):
            batch.drop_column(col)
