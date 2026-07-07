from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from api.models_db import AnalysisRun, MentorComment, MentorShare, Upload


ROOT = Path(__file__).resolve().parents[1]


def _upgrade_temp_database(db_url: str) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "head")


def _column_map(inspector, table_name: str):
    return {column["name"]: column for column in inspector.get_columns(table_name)}


def _foreign_key_targets(inspector, table_name: str):
    targets = {}
    for fk in inspector.get_foreign_keys(table_name):
        for constrained, referred in zip(fk["constrained_columns"], fk["referred_columns"]):
            targets[constrained] = (fk["referred_table"], referred)
    return targets


def test_alembic_head_matches_phase8_schema_contract(tmp_path, monkeypatch):
    db_path = tmp_path / "migration_drift.db"
    db_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DB_URL", db_url)

    _upgrade_temp_database(db_url)

    engine = create_engine(db_url)
    try:
        inspector = inspect(engine)

        mentor_share_columns = _column_map(inspector, "mentor_shares")
        assert mentor_share_columns["token"]["type"].length == 128
        assert MentorShare.__table__.c.token.type.length == 128

        unique_token_indexes = [
            index
            for index in inspector.get_indexes("mentor_shares")
            if index.get("unique") and index.get("column_names") == ["token"]
        ]
        unique_token_constraints = [
            constraint
            for constraint in inspector.get_unique_constraints("mentor_shares")
            if constraint.get("column_names") == ["token"]
        ]
        assert unique_token_indexes or unique_token_constraints

        analysis_columns = _column_map(inspector, "analysis_runs")
        assert "upload_id" in analysis_columns
        assert "created_at" in analysis_columns
        assert "upload_id" in AnalysisRun.__table__.c
        analysis_fks = _foreign_key_targets(inspector, "analysis_runs")
        assert analysis_fks["upload_id"] == ("uploads", "id")

        upload_columns = _column_map(inspector, "uploads")
        for column_name in [
            "created_at",
            "file_type",
            "size_bytes",
            "checksum_sha256",
            "original_filename",
            "storage_key",
            "status",
        ]:
            assert column_name in upload_columns
            assert column_name in Upload.__table__.c
        assert upload_columns["checksum_sha256"]["type"].length == 64
        assert Upload.__table__.c.checksum_sha256.type.length == 64

        comment_columns = _column_map(inspector, "mentor_comments")
        for column_name in [
            "share_id",
            "project_id",
            "author_name",
            "author_email",
            "text",
            "created_at",
            "updated_at",
            "deleted_at",
        ]:
            assert column_name in comment_columns
            assert column_name in MentorComment.__table__.c
        comment_fks = _foreign_key_targets(inspector, "mentor_comments")
        assert comment_fks["share_id"] == ("mentor_shares", "id")
        assert comment_fks["project_id"] == ("projects", "id")
    finally:
        engine.dispose()
