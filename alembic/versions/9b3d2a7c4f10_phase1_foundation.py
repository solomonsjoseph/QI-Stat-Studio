"""phase1_foundation

Revision ID: 9b3d2a7c4f10
Revises: 5be9d78e473c
Create Date: 2026-07-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9b3d2a7c4f10"
down_revision: Union[str, Sequence[str], None] = "5be9d78e473c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}


def _rebuild_existing_foreign_keys() -> None:
    with op.batch_alter_table("uploads", recreate="always", naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_constraint("fk_uploads_project_id_projects", type_="foreignkey")
        batch.create_foreign_key("fk_uploads_project_id_projects", "projects", ["project_id"], ["id"], ondelete="CASCADE")

    with op.batch_alter_table("intake_answers", recreate="always", naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_constraint("fk_intake_answers_project_id_projects", type_="foreignkey")
        batch.create_foreign_key("fk_intake_answers_project_id_projects", "projects", ["project_id"], ["id"], ondelete="CASCADE")

    with op.batch_alter_table("analysis_runs", recreate="always", naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_constraint("fk_analysis_runs_project_id_projects", type_="foreignkey")
        batch.drop_constraint("fk_analysis_runs_upload_id_uploads", type_="foreignkey")
        batch.create_foreign_key("fk_analysis_runs_project_id_projects", "projects", ["project_id"], ["id"], ondelete="CASCADE")
        batch.create_foreign_key("fk_analysis_runs_upload_id_uploads", "uploads", ["upload_id"], ["id"], ondelete="CASCADE")

    with op.batch_alter_table("audit_log", recreate="always", naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_constraint("fk_audit_log_project_id_projects", type_="foreignkey")
        batch.create_foreign_key("fk_audit_log_project_id_projects", "projects", ["project_id"], ["id"], ondelete="CASCADE")

    with op.batch_alter_table("edit_history", recreate="always", naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_constraint("fk_edit_history_project_id_projects", type_="foreignkey")
        batch.create_foreign_key("fk_edit_history_project_id_projects", "projects", ["project_id"], ["id"], ondelete="CASCADE")

    with op.batch_alter_table("mentor_shares", recreate="always", naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_constraint("fk_mentor_shares_project_id_projects", type_="foreignkey")
        batch.drop_constraint("fk_mentor_shares_regenerated_from_id", type_="foreignkey")
        batch.create_foreign_key("fk_mentor_shares_project_id_projects", "projects", ["project_id"], ["id"], ondelete="CASCADE")
        batch.create_foreign_key("fk_mentor_shares_regenerated_from_id", "mentor_shares", ["regenerated_from_id"], ["id"], ondelete="SET NULL")

    with op.batch_alter_table("failure_log", recreate="always", naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_constraint("fk_failure_log_project_id_projects", type_="foreignkey")
        batch.create_foreign_key("fk_failure_log_project_id_projects", "projects", ["project_id"], ["id"], ondelete="SET NULL")
        batch.create_foreign_key("fk_failure_log_upload_id_uploads", "uploads", ["upload_id"], ["id"], ondelete="SET NULL")
        batch.create_foreign_key("fk_failure_log_run_id_analysis_runs", "analysis_runs", ["run_id"], ["id"], ondelete="SET NULL")



def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, server_default="resident"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("disabled_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
    )
    op.create_index("ix_user_sessions_token_hash", "user_sessions", ["token_hash"], unique=True)

    op.add_column("projects", sa.Column("owner_user_id", sa.Integer(), nullable=True))
    op.add_column("projects", sa.Column("archived_at", sa.DateTime(), nullable=True))
    with op.batch_alter_table("projects") as batch:
        batch.create_foreign_key("fk_projects_owner_user_id_users", "users", ["owner_user_id"], ["id"], ondelete="SET NULL")

    op.add_column("uploads", sa.Column("created_at", sa.DateTime(), nullable=True))
    op.add_column("uploads", sa.Column("file_type", sa.String(20), nullable=True))
    op.add_column("uploads", sa.Column("size_bytes", sa.Integer(), nullable=True))
    op.add_column("uploads", sa.Column("checksum_sha256", sa.String(64), nullable=True))
    op.add_column("uploads", sa.Column("original_filename", sa.String(255), nullable=True))
    op.add_column("uploads", sa.Column("storage_key", sa.String(512), nullable=True))
    op.add_column("uploads", sa.Column("status", sa.String(20), nullable=True))
    op.execute("UPDATE uploads SET original_filename = filename WHERE original_filename IS NULL")
    op.execute("UPDATE uploads SET storage_key = filename WHERE storage_key IS NULL")
    op.execute("UPDATE uploads SET size_bytes = 0 WHERE size_bytes IS NULL")
    op.execute("UPDATE uploads SET checksum_sha256 = '' WHERE checksum_sha256 IS NULL")
    op.execute("UPDATE uploads SET status = 'active' WHERE status IS NULL")
    op.execute("UPDATE uploads SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
    op.execute("UPDATE uploads SET file_type = CASE WHEN lower(filename) LIKE '%.csv' THEN 'csv' WHEN lower(filename) LIKE '%.xlsx' THEN 'xlsx' WHEN lower(filename) LIKE '%.xls' THEN 'xls' ELSE 'unknown' END WHERE file_type IS NULL")

    op.add_column("analysis_runs", sa.Column("upload_id", sa.Integer(), nullable=True))
    op.add_column("analysis_runs", sa.Column("created_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE analysis_runs SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
    op.execute("UPDATE analysis_runs SET upload_id = (SELECT uploads.id FROM uploads WHERE uploads.project_id = analysis_runs.project_id ORDER BY uploads.id LIMIT 1) WHERE upload_id IS NULL")
    with op.batch_alter_table("analysis_runs") as batch:
        batch.create_foreign_key("fk_analysis_runs_upload_id_uploads", "uploads", ["upload_id"], ["id"], ondelete="CASCADE")

    op.add_column("mentor_shares", sa.Column("created_at", sa.DateTime(), nullable=True))
    op.add_column("mentor_shares", sa.Column("expires_at", sa.DateTime(), nullable=True))
    op.add_column("mentor_shares", sa.Column("revoked_at", sa.DateTime(), nullable=True))
    op.add_column("mentor_shares", sa.Column("regenerated_from_id", sa.Integer(), nullable=True))
    op.execute("UPDATE mentor_shares SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
    op.create_index("uq_mentor_shares_token", "mentor_shares", ["token"], unique=True)
    with op.batch_alter_table("mentor_shares") as batch:
        batch.alter_column("token", existing_type=sa.String(64), type_=sa.String(128))
        batch.create_foreign_key("fk_mentor_shares_regenerated_from_id", "mentor_shares", ["regenerated_from_id"], ["id"], ondelete="SET NULL")

    op.create_table(
        "mentor_comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("share_id", sa.Integer(), sa.ForeignKey("mentor_shares.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_name", sa.String(255), nullable=False),
        sa.Column("author_email", sa.String(255), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "ai_usage_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("prompt_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
    )
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True),
        sa.Column("share_id", sa.Integer(), sa.ForeignKey("mentor_shares.id", ondelete="CASCADE"), nullable=True),
        sa.Column("kind", sa.String(100), nullable=False),
        sa.Column("recipient_email", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
    )

    op.add_column("failure_log", sa.Column("message", sa.Text(), nullable=True))
    op.add_column("failure_log", sa.Column("route", sa.String(255), nullable=True))
    op.add_column("failure_log", sa.Column("action", sa.String(100), nullable=True))
    op.add_column("failure_log", sa.Column("request_id", sa.String(64), nullable=True))
    op.add_column("failure_log", sa.Column("upload_id", sa.Integer(), nullable=True))
    op.add_column("failure_log", sa.Column("run_id", sa.Integer(), nullable=True))
    op.add_column("failure_log", sa.Column("safe_context_json", sa.Text(), nullable=True, server_default="{}"))
    _rebuild_existing_foreign_keys()


def downgrade() -> None:
    with op.batch_alter_table("failure_log", naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_constraint("fk_failure_log_run_id_analysis_runs", type_="foreignkey")
        batch.drop_constraint("fk_failure_log_upload_id_uploads", type_="foreignkey")
        batch.drop_constraint("fk_failure_log_project_id_projects", type_="foreignkey")
    op.drop_column("failure_log", "safe_context_json")
    op.drop_column("failure_log", "run_id")
    op.drop_column("failure_log", "upload_id")
    op.drop_column("failure_log", "request_id")
    op.drop_column("failure_log", "action")
    op.drop_column("failure_log", "route")
    op.drop_column("failure_log", "message")
    op.drop_table("notification_deliveries")
    op.drop_table("ai_usage_events")
    op.drop_table("mentor_comments")
    with op.batch_alter_table("mentor_shares") as batch:
        batch.drop_constraint("fk_mentor_shares_regenerated_from_id", type_="foreignkey")
    op.drop_index("uq_mentor_shares_token", table_name="mentor_shares")
    op.drop_column("mentor_shares", "regenerated_from_id")
    op.drop_column("mentor_shares", "revoked_at")
    op.drop_column("mentor_shares", "expires_at")
    op.drop_column("mentor_shares", "created_at")
    with op.batch_alter_table("analysis_runs") as batch:
        batch.drop_constraint("fk_analysis_runs_upload_id_uploads", type_="foreignkey")
    op.drop_column("analysis_runs", "created_at")
    op.drop_column("analysis_runs", "upload_id")
    op.drop_column("uploads", "status")
    op.drop_column("uploads", "storage_key")
    op.drop_column("uploads", "original_filename")
    op.drop_column("uploads", "checksum_sha256")
    op.drop_column("uploads", "size_bytes")
    op.drop_column("uploads", "file_type")
    op.drop_column("uploads", "created_at")
    with op.batch_alter_table("projects") as batch:
        batch.drop_constraint("fk_projects_owner_user_id_users", type_="foreignkey")
    op.drop_column("projects", "archived_at")
    op.drop_column("projects", "owner_user_id")
    op.drop_index("ix_user_sessions_token_hash", table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
