"""API surface smoke tests — no database required."""

from app.core.config import get_settings


def test_app_builds(api_app):
    assert api_app.title == "NewNews"


async def test_healthz_is_open(api):
    response = await api.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers.get("X-Correlation-ID")


async def test_readyz_reports_readiness_or_redacted_error(api):
    response = await api.get("/readyz")
    assert response.status_code in (200, 503)
    body = response.json()
    if response.status_code == 200:
        assert body == {"status": "ready"}
    else:  # 503: class + bounded message, never credentials
        assert body["status"] == "unavailable"
        assert ":" in body["detail"]
        assert len(body["detail"]) <= 400 + 64


def test_safe_db_error_redacts_url_credentials():
    from app.api.routers.health import safe_db_error

    exc = RuntimeError(
        "connection failed: postgresql+psycopg://newnews:s3cr3t@db.example:5432/news?sslmode=require"
    )
    message = safe_db_error(exc)
    assert "s3cr3t" not in message
    assert "://***@db.example" in message
    assert safe_db_error(RuntimeError("")) == "RuntimeError"


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
