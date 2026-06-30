"""initial_schema_full

Revision ID: 5be9d78e473c
Revises: cc61920dee93
Create Date: 2026-06-30 07:01:50.525624

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5be9d78e473c'
down_revision: Union[str, Sequence[str], None] = 'cc61920dee93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'projects',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('title', sa.String(255), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(50), server_default='draft', nullable=True),
        sa.Column('deadline', sa.String(20), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_table(
        'uploads',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=True),
        sa.Column('filename', sa.String(255), nullable=True),
        sa.Column('column_map', sa.Text(), server_default='{}', nullable=True),
        sa.Column('col_types', sa.Text(), server_default='{}', nullable=True),
        sa.Column('quality_flags', sa.Text(), server_default='[]', nullable=True),
        sa.Column('acknowledged_flags', sa.Text(), nullable=True),
        sa.Column('encrypted_path', sa.String(512), nullable=True),
    )
    op.create_table(
        'intake_answers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=True),
        sa.Column('question_key', sa.String(10), nullable=True),
        sa.Column('answer', sa.Text(), nullable=True),
        sa.Column('is_unsure', sa.Boolean(), server_default='0', nullable=True),
    )
    op.create_table(
        'analysis_runs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=True),
        sa.Column('template', sa.String(50), nullable=True),
        sa.Column('parameters', sa.Text(), server_default='{}', nullable=True),
        sa.Column('result_json', sa.Text(), server_default='{}', nullable=True),
        sa.Column('code_r', sa.Text(), server_default='', nullable=True),
        sa.Column('code_spss', sa.Text(), server_default='', nullable=True),
        sa.Column('code_sas', sa.Text(), server_default='', nullable=True),
    )
    op.create_table(
        'audit_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=True),
        sa.Column('action', sa.String(100), nullable=True),
        sa.Column('metadata_json', sa.Text(), server_default='{}', nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
    )
    op.create_table(
        'edit_history',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=True),
        sa.Column('field', sa.String(100), nullable=True),
        sa.Column('original_text', sa.Text(), nullable=True),
        sa.Column('edited_text', sa.Text(), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
    )
    op.create_table(
        'mentor_shares',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=True),
        sa.Column('token', sa.String(64), nullable=True),
        sa.Column('mentor_email', sa.String(255), nullable=True),
        sa.Column('comments_json', sa.Text(), server_default='[]', nullable=True),
    )
    op.create_table(
        'failure_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=True),
        sa.Column('error_type', sa.String(100), nullable=True),
        sa.Column('template', sa.String(50), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
    )
    op.create_table(
        'app_settings',
        sa.Column('key', sa.String(100), primary_key=True),
        sa.Column('value', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('app_settings')
    op.drop_table('failure_log')
    op.drop_table('mentor_shares')
    op.drop_table('edit_history')
    op.drop_table('audit_log')
    op.drop_table('analysis_runs')
    op.drop_table('intake_answers')
    op.drop_table('uploads')
    op.drop_table('projects')
