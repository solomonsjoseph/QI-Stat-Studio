import os
from pathlib import Path

_pid = os.getpid()
_db_file = f"/tmp/test_qi_stat_studio_{_pid}.db"
os.environ.setdefault("DB_URL", f"sqlite:///{_db_file}")
_db_path = Path(_db_file)

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

@pytest.fixture
def mock_llm():
    import json
    from unittest.mock import patch
    from types import SimpleNamespace

    queue = []

    def push(content):
        if isinstance(content, dict):
            content = json.dumps(content)
        queue.append(content)

    def side_effect(*args, **kwargs):
        if queue:
            resp_content = queue.pop(0)
        else:
            resp_content = "{}"
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=resp_content))])

    with patch("api.routers.ai.litellm.completion", side_effect=side_effect) as mocked:
        mocked.push = push
        yield mocked
