"""drop_mentor_share_comments_json

Revision ID: c4e1f8a2d9b6
Revises: 9b3d2a7c4f10
Create Date: 2026-07-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4e1f8a2d9b6"
down_revision: Union[str, Sequence[str], None] = "9b3d2a7c4f10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("mentor_shares") as batch:
        batch.drop_column("comments_json")


def downgrade() -> None:
    with op.batch_alter_table("mentor_shares") as batch:
        batch.add_column(sa.Column("comments_json", sa.Text(), nullable=True))
