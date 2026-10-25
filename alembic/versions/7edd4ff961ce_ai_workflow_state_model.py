"""ai_workflow_state_model

Revision ID: 7edd4ff961ce
Revises: ed3f76774c35
Create Date: 2026-09-09 10:39:06.288179

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7edd4ff961ce'
down_revision: Union[str, Sequence[str], None] = 'ed3f76774c35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False))
        batch.add_column(sa.Column("workflow_phase", sa.String(32), server_default="intake", nullable=False))
        batch.add_column(sa.Column("ai_plan_history", sa.Text(), nullable=True))
        batch.add_column(sa.Column("inputs_fingerprint", sa.String(64), nullable=True))

    with op.batch_alter_table("uploads") as batch:
        batch.add_column(sa.Column("dataset_profile", sa.Text(), nullable=True))
        batch.add_column(sa.Column("phi_scan_detail", sa.Text(), nullable=True))
        batch.add_column(sa.Column("column_roles", sa.Text(), server_default="{}", nullable=False))

    with op.batch_alter_table("edit_history", recreate="always", naming_convention=NAMING_CONVENTION) as batch:
        batch.add_column(sa.Column("run_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_edit_history_run_id_analysis_runs",
            "analysis_runs",
            ["run_id"],
            ["id"],
            ondelete="CASCADE",
        )

    op.drop_table("intake_answers")


def downgrade() -> None:
    op.create_table(
        "intake_answers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True),
        sa.Column("question_key", sa.String(10), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("is_unsure", sa.Boolean(), server_default="0", nullable=True),
    )

    with op.batch_alter_table("edit_history", recreate="always", naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_constraint("fk_edit_history_run_id_analysis_runs", type_="foreignkey")
        batch.drop_column("run_id")

    with op.batch_alter_table("uploads") as batch:
        batch.drop_column("column_roles")
        batch.drop_column("phi_scan_detail")
        batch.drop_column("dataset_profile")

    with op.batch_alter_table("projects") as batch:
        batch.drop_column("inputs_fingerprint")
        batch.drop_column("ai_plan_history")
        batch.drop_column("workflow_phase")
        batch.drop_column("schema_version")
