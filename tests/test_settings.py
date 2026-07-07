import os
os.environ.setdefault("FERNET_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")



def _admin(client):
    resp = client.post("/auth/register", json={"email": "admin@example.com", "password": "password123"})
    assert resp.status_code == 200, resp.text


def _settings_map(items):
    return {item["key"]: item["value"] for item in items}


def test_get_settings_empty(client):
    _admin(client)
    resp = client.get("/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert "clinic_name" in _settings_map(data)


def test_upsert_and_read_setting(client):
    _admin(client)
    resp = client.put("/settings", json={"key": "clinic_name", "value": "Rutgers IM"})
    assert resp.status_code == 200
    resp = client.get("/settings")
    assert _settings_map(resp.json())["clinic_name"] == "Rutgers IM"


def test_upsert_updates_existing(client):
    _admin(client)
    client.put("/settings", json={"key": "clinic_name", "value": "v1"})
    client.put("/settings", json={"key": "clinic_name", "value": "v2"})
    resp = client.get("/settings")
    assert _settings_map(resp.json())["clinic_name"] == "v2"
