"""tighten_backfilled_not_null_columns

Revision ID: d4a1e6f0b8c2
Revises: c4e1f8a2d9b6
Create Date: 2026-07-09 00:00:00.000000

Phase1 (9b3d2a7c4f10) backfilled uploads.{created_at,file_type,size_bytes,
checksum_sha256,original_filename,storage_key,status}, analysis_runs.created_at,
and mentor_shares.created_at with real values but left the columns nullable at
the DB level while api/models_db.py declares them nullable=False. This closes
that model-vs-migrated-schema gap without touching the already-applied
9b3d2a7c4f10 migration. Every column tightened here was already fully backfilled
by 9b3d2a7c4f10 (see its UPDATE statements), so this is safe to run against any
DB that already sits at or past that revision.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4a1e6f0b8c2"
down_revision: Union[str, Sequence[str], None] = "c4e1f8a2d9b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Belt-and-suspenders: ensure no NULLs slipped in on a DB that migrated
    # through 9b3d2a7c4f10 before this revision existed, so the NOT NULL
    # tightening below never fails on replay.
    op.execute("UPDATE uploads SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
    op.execute("UPDATE uploads SET file_type = 'unknown' WHERE file_type IS NULL")
    op.execute("UPDATE uploads SET size_bytes = 0 WHERE size_bytes IS NULL")
    op.execute("UPDATE uploads SET checksum_sha256 = '' WHERE checksum_sha256 IS NULL")
    op.execute("UPDATE uploads SET original_filename = filename WHERE original_filename IS NULL")
    op.execute("UPDATE uploads SET storage_key = filename WHERE storage_key IS NULL")
    op.execute("UPDATE uploads SET status = 'active' WHERE status IS NULL")
    with op.batch_alter_table("uploads") as batch:
        batch.alter_column("created_at", existing_type=sa.DateTime(), nullable=False)
        batch.alter_column("file_type", existing_type=sa.String(20), nullable=False)
        batch.alter_column("size_bytes", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("checksum_sha256", existing_type=sa.String(64), nullable=False)
        batch.alter_column("original_filename", existing_type=sa.String(255), nullable=False)
        batch.alter_column("storage_key", existing_type=sa.String(512), nullable=False)
        batch.alter_column("status", existing_type=sa.String(20), nullable=False)

    op.execute("UPDATE analysis_runs SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
    with op.batch_alter_table("analysis_runs") as batch:
        batch.alter_column("created_at", existing_type=sa.DateTime(), nullable=False)

    op.execute("UPDATE mentor_shares SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
    with op.batch_alter_table("mentor_shares") as batch:
        batch.alter_column("created_at", existing_type=sa.DateTime(), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("mentor_shares") as batch:
        batch.alter_column("created_at", existing_type=sa.DateTime(), nullable=True)

    with op.batch_alter_table("analysis_runs") as batch:
        batch.alter_column("created_at", existing_type=sa.DateTime(), nullable=True)

    with op.batch_alter_table("uploads") as batch:
        batch.alter_column("status", existing_type=sa.String(20), nullable=True)
        batch.alter_column("storage_key", existing_type=sa.String(512), nullable=True)
        batch.alter_column("original_filename", existing_type=sa.String(255), nullable=True)
        batch.alter_column("checksum_sha256", existing_type=sa.String(64), nullable=True)
        batch.alter_column("size_bytes", existing_type=sa.Integer(), nullable=True)
        batch.alter_column("file_type", existing_type=sa.String(20), nullable=True)
        batch.alter_column("created_at", existing_type=sa.DateTime(), nullable=True)
