"""resident replies, resolved comments and mentor approval

Revision ID: f1b7c3a9d205
Revises: a8f3c1d27e55
Create Date: 2026-10-24 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1b7c3a9d205"
down_revision: Union[str, Sequence[str], None] = "a8f3c1d27e55"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("mentor_comments") as batch:
        batch.add_column(sa.Column("resident_reply", sa.Text(), nullable=True))
        batch.add_column(sa.Column("addressed_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("resolved_at", sa.DateTime(), nullable=True))
    with op.batch_alter_table("mentor_shares") as batch:
        batch.add_column(sa.Column("approved_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("approved_by_name", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("approved_note", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("mentor_shares") as batch:
        batch.drop_column("approved_note")
        batch.drop_column("approved_by_name")
        batch.drop_column("approved_at")
    with op.batch_alter_table("mentor_comments") as batch:
        batch.drop_column("resolved_at")
        batch.drop_column("addressed_at")
        batch.drop_column("resident_reply")
