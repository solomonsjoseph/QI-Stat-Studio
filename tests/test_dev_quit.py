"""Local quit endpoint (non-production only)."""

from unittest.mock import patch

from api.config import settings


def _register(client, email="quitter@example.com"):
    response = client.post("/auth/register", json={"email": email, "password": "password123"})
    assert response.status_code == 200, response.text


def test_dev_quit_stops_outside_production(client, monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    _register(client)
    with patch("api.routers.dev.threading.Thread") as thread_cls:
        response = client.post("/dev/quit")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["stopped"] is True
    thread_cls.assert_called_once()


def test_dev_quit_hidden_in_production(client, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    _register(client, email="prodquit@example.com")
    response = client.post("/dev/quit")
    assert response.status_code == 404
