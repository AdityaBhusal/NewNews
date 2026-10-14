"""API surface smoke tests — no database required."""

from app.core.config import get_settings


def test_app_builds(api_app):
    assert api_app.title == "NewNews"


async def test_healthz_is_open(api):
    response = await api.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers.get("X-Correlation-ID")


async def test_root_lists_entry_points(api):
    response = await api.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["docs"] == "/docs"
    assert body["api"] == get_settings().api_prefix


async def test_openapi_schema_generated(api_app):
    from fastapi.testclient import TestClient

    # TestClient is sync but only used here for schema generation (no DB access).
    with TestClient(api_app) as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/items" in paths
    assert "/api/v1/news" in paths
    assert "/api/v1/events" in paths
    assert "/api/v1/clients" in paths


async def test_ingest_requires_api_key(api):
    response = await api.post(
        "/api/v1/items",
        json={"body": "some text", "source_key": "k1"},
    )
    assert response.status_code == 401


async def test_news_requires_api_key(api):
    response = await api.get("/api/v1/news")
    assert response.status_code == 401


async def test_clients_requires_admin_key(api):
    response = await api.post("/api/v1/clients", json={"name": "nope"})
    assert response.status_code == 403
