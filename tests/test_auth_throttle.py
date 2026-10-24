"""Sign-in throttling, generic failures and password hash upgrades (OWASP Authentication and Password Storage)."""
import os

os.environ.setdefault("FERNET_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")

from api import throttle
from api.config import settings
from api.database import SessionLocal
from api.models_db import AuditLog, User

PASSWORD = "password123"


def _register(client, email="throttle@example.com"):
    assert client.post("/auth/register", json={"email": email, "password": PASSWORD}).status_code == 200
    client.post("/auth/logout")


def _login(client, email, password):
    return client.post("/auth/login", json={"email": email, "password": password})


def test_five_wrong_passwords_lock_the_account_even_for_the_right_password(client):
    _register(client)
    for _ in range(4):
        assert _login(client, "throttle@example.com", "wrong-password").status_code == 401
    assert _login(client, "throttle@example.com", "wrong-password").status_code == 401  # the fifth failure locks it
    locked = _login(client, "throttle@example.com", PASSWORD)
    assert locked.status_code == 429
    assert "Try again in" in locked.json()["error"]["message"] and "Retry-After" in locked.headers


def test_an_unknown_email_is_throttled_the_same_way_so_lockout_reveals_nothing(client):
    for _ in range(5):
        assert _login(client, "nobody@example.com", "whatever123").status_code == 401
    assert _login(client, "nobody@example.com", "whatever123").status_code == 429


def test_a_successful_sign_in_clears_earlier_failures(client):
    _register(client)
    for _ in range(4):
        _login(client, "throttle@example.com", "wrong-password")
    assert _login(client, "throttle@example.com", PASSWORD).status_code == 200
    client.post("/auth/logout")
    for _ in range(4):
        assert _login(client, "throttle@example.com", "wrong-password").status_code == 401  # a fresh count, not 8 in a row


def test_the_lockout_ends_after_its_duration(client, monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(throttle, "_now", lambda: clock["t"])
    _register(client)
    for _ in range(5):
        _login(client, "throttle@example.com", "wrong-password")
    assert _login(client, "throttle@example.com", PASSWORD).status_code == 429
    clock["t"] += throttle.LOCK + 1
    assert _login(client, "throttle@example.com", PASSWORD).status_code == 200


def test_one_address_cannot_create_accounts_in_bulk(client, monkeypatch):
    monkeypatch.setattr(throttle, "IP_REGISTER_LIMIT", 3)
    for i in range(3):
        assert client.post("/auth/register", json={"email": f"bulk{i}@example.com", "password": PASSWORD}).status_code == 200
        client.post("/auth/logout")
    assert client.post("/auth/register", json={"email": "bulk3@example.com", "password": PASSWORD}).status_code == 429


def test_failures_are_logged_without_the_email_address(client):
    _login(client, "someone@example.com", "wrong-password")
    with SessionLocal() as db:
        rows = db.query(AuditLog).filter(AuditLog.action == "login_failed").all()
    assert len(rows) == 1 and "someone@example.com" not in rows[0].metadata_json


def test_an_older_password_hash_is_upgraded_on_the_next_sign_in(client, monkeypatch):
    _register(client)
    monkeypatch.setattr(settings, "password_iterations", 2000)
    assert _login(client, "throttle@example.com", PASSWORD).status_code == 200
    with SessionLocal() as db:
        stored = db.query(User).filter_by(email="throttle@example.com").one().password_hash
    assert stored.startswith("pbkdf2_sha256$2000$")
    client.post("/auth/logout")
    assert _login(client, "throttle@example.com", PASSWORD).status_code == 200  # the upgraded hash still verifies


def test_the_production_default_meets_the_owasp_minimum():
    from api.config import Settings
    assert Settings.model_fields["password_iterations"].default >= 600_000
