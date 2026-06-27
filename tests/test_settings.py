import os
os.environ.setdefault("FERNET_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")

from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


def test_get_settings_empty():
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_upsert_and_read_setting():
    client.put("/settings", json={"key": "clinic_name", "value": "Rutgers IM"})
    resp = client.get("/settings")
    assert resp.json().get("clinic_name") == "Rutgers IM"


def test_upsert_updates_existing():
    client.put("/settings", json={"key": "clinic_name", "value": "v1"})
    client.put("/settings", json={"key": "clinic_name", "value": "v2"})
    resp = client.get("/settings")
    assert resp.json()["clinic_name"] == "v2"
