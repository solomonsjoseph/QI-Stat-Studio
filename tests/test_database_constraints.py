import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from api.database import SessionLocal
from api.models_db import Upload


def test_sqlite_foreign_keys_are_enabled():
    with SessionLocal() as db:
        assert db.execute(text("PRAGMA foreign_keys")).scalar() == 1
        db.add(Upload(project_id=999999, filename="bad.csv", encrypted_path="missing"))
        with pytest.raises(IntegrityError):
            db.commit()
