from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine

from api.database import Base
import api.models_db  # noqa: F401 - register all metadata tables


ROOT = Path(__file__).resolve().parents[1]


def _table_columns(db_path: Path) -> dict[str, set[str]]:
    connection = sqlite3.connect(db_path)
    try:
        table_rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name != 'alembic_version'"
        ).fetchall()
        columns: dict[str, set[str]] = {}
        for (table_name,) in table_rows:
            info = connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
            columns[table_name] = {row[1] for row in info}
        return columns
    finally:
        connection.close()


def test_alembic_head_matches_base_metadata_column_sets(tmp_path):
    migration_db = tmp_path / "mig.db"
    metadata_db = tmp_path / "metadata.db"

    env = os.environ.copy()
    env.update(
        {
            "DB_URL": f"sqlite:///{migration_db}",
            "FERNET_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            "PYTHONPATH": ".",
        }
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    metadata_engine = create_engine(f"sqlite:///{metadata_db}")
    try:
        Base.metadata.create_all(bind=metadata_engine)
    finally:
        metadata_engine.dispose()

    migration_columns = _table_columns(migration_db)
    metadata_columns = _table_columns(metadata_db)

    assert migration_columns == metadata_columns
    assert "comments_json" not in migration_columns["mentor_shares"]
    assert "comments_json" not in metadata_columns["mentor_shares"]
