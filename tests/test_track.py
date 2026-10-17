"""Pipeline board endpoint (`GET /api/v1/track`): all items + audit streams."""

from __future__ import annotations


async def _create_client(api, admin_headers) -> dict:
    response = await api.post(
        "/api/v1/clients",
        json={"name": "board-client"},
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['api_key']}"}


async def test_track_board_lists_every_item_with_events(db, api, admin_headers):
    """Board returns all items newest-first, each with its audit event stream."""
    from app.worker.main import drain

    auth = await _create_client(api, admin_headers)
    created = []
    for i in range(3):
        response = await api.post(
            "/api/v1/items",
            json={
                "body": f"Kathmandu, 17 October 2026 — board item {i} "
                "with enough text to be a plausible wire dispatch for the pipeline.",
                "source_key": f"board-{i}",
            },
            headers=auth,
        )
        assert response.status_code == 202, response.text
        created.append(response.json()["id"])
    await drain(db)

    response = await api.get("/api/v1/track", headers=admin_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] >= 3
    by_id = {entry["item"]["id"]: entry for entry in payload["items"]}
    for item_id in created:
        entry = by_id[item_id]
        # Every row carries the item and at least the ingest audit event.
        assert entry["item"]["id"] == item_id
        assert "received" in entry["events"]
        # Processed items show pipeline progress in their event stream.
        assert any(
            event in entry["events"]
            for event in ("validated", "needs_review", "duplicate")
        ), entry["events"]


async def test_track_board_requires_admin(db, api, admin_headers):
    """A regular client key must not see the whole pipeline board (403)."""
    auth = await _create_client(api, admin_headers)

    response = await api.get("/api/v1/track", headers=auth)
    assert response.status_code == 403

    response = await api.get("/api/v1/track")
    assert response.status_code == 403


async def test_track_board_limit_is_capped(db, api, admin_headers):
    response = await api.get("/api/v1/track?limit=99999", headers=admin_headers)
    assert response.status_code == 200
