"""ai_workflow_foundation

Revision ID: ed3f76774c35
Revises: d4a1e6f0b8c2
Create Date: 2026-08-20 00:00:00.000000

Foundational-slice schema for the AI-guided workflow rework: PHI-gate
bookkeeping and data-dictionary storage on uploads, plus JSON state columns
on projects for the (deferred) AI clarification and analysis-plan stages.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ed3f76774c35"
down_revision: Union[str, Sequence[str], None] = "d4a1e6f0b8c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("uploads") as batch:
        batch.add_column(sa.Column("phi_scan_status", sa.String(20), server_default="clean", nullable=False))
        batch.add_column(sa.Column("dictionary_filename", sa.String(255), nullable=True))
        batch.add_column(sa.Column("dictionary_text", sa.Text(), nullable=True))

    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("ai_clarification_state", sa.Text(), nullable=True))
        batch.add_column(sa.Column("ai_project_design", sa.Text(), nullable=True))
        batch.add_column(sa.Column("ai_analysis_plan", sa.Text(), nullable=True))
        batch.add_column(sa.Column("data_collection_notes", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("data_collection_notes")
        batch.drop_column("ai_analysis_plan")
        batch.drop_column("ai_project_design")
        batch.drop_column("ai_clarification_state")

    with op.batch_alter_table("uploads") as batch:
        batch.drop_column("dictionary_text")
        batch.drop_column("dictionary_filename")
        batch.drop_column("phi_scan_status")
