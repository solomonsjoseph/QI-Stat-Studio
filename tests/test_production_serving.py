from fastapi.testclient import TestClient
from starlette.applications import Starlette

from api.main import SPAStaticFiles


def test_api_prefix_routes_to_backend(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_prefix_reaches_protected_router(client):
    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/json")


def test_unknown_api_prefixed_route_returns_json_404_not_spa(client):
    response = client.get("/api/definitely-not-a-route")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["error"]["code"] == "HTTP_404"
    assert "request_id" in body["error"]


def test_spa_static_files_falls_back_to_index_for_client_routes(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><body>QI SPA shell</body></html>", encoding="utf-8")

    app = Starlette()
    app.mount("/", SPAStaticFiles(directory=dist, html=True), name="frontend")

    with TestClient(app) as client:
        client_route = client.get("/mentor/xyz")
        index_route = client.get("/index.html")

    assert client_route.status_code == 200
    assert "QI SPA shell" in client_route.text
    assert index_route.status_code == 200
    assert "QI SPA shell" in index_route.text
