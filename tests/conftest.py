import os
from pathlib import Path

os.environ.setdefault("DB_URL", "sqlite:///./test_qi_stat_studio.db")

_db_path = Path("test_qi_stat_studio.db")
if _db_path.exists():
    _db_path.unlink()

import api.models_db  # noqa: E402,F401 - register models
from api.database import Base, engine  # noqa: E402
from api.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def create_test_schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    if _db_path.exists():
        _db_path.unlink()


@pytest.fixture(autouse=True)
def clean_database():
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    yield


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_client(client):
    response = client.post("/auth/register", json={"email": "owner@example.com", "password": "password123"})
    assert response.status_code == 200, response.text
    return client
