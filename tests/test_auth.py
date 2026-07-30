from api.database import SessionLocal
from api.models_db import UserSession


def test_register_first_user_admin_sets_session_cookie(client):
    response = client.post("/auth/register", json={"email": "Admin@Example.com", "password": "password123"})

    assert response.status_code == 200, response.text
    assert response.json()["email"] == "admin@example.com"
    assert response.json()["role"] == "admin"
    assert "qiss_session" in response.cookies
    assert client.get("/auth/me").json()["email"] == "admin@example.com"


def test_later_user_is_resident_and_login_logout_revokes_session(client):
    assert client.post("/auth/register", json={"email": "admin@example.com", "password": "password123"}).status_code == 200
    assert client.post("/auth/logout").status_code == 200

    resident = client.post("/auth/register", json={"email": "resident@example.com", "password": "password123"})
    assert resident.status_code == 200, resident.text
    assert resident.json()["role"] == "resident"

    assert client.post("/auth/logout").status_code == 200
    assert client.get("/auth/me").status_code == 401

    login = client.post("/auth/login", json={"email": "resident@example.com", "password": "password123"})
    assert login.status_code == 200, login.text
    assert login.json()["email"] == "resident@example.com"

    logout = client.post("/auth/logout")
    assert logout.status_code == 200
    assert client.get("/auth/me").status_code == 401

    with SessionLocal() as db:
        assert db.query(UserSession).filter(UserSession.revoked_at.is_not(None)).count() >= 1


def test_duplicate_register_and_bad_login_return_errors(client):
    assert client.post("/auth/register", json={"email": "user@example.com", "password": "password123"}).status_code == 200
    duplicate = client.post("/auth/register", json={"email": "user@example.com", "password": "password123"})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "HTTP_409"

    assert client.post("/auth/logout").status_code == 200
    bad = client.post("/auth/login", json={"email": "user@example.com", "password": "wrongpassword"})
    assert bad.status_code == 401
    assert bad.json()["error"]["request_id"]
