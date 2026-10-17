"""Pipeline board endpoint (`GET /api/v1/track`): all items + audit streams,
plus the live admin board stream (`GET /api/v1/track/events`)."""

from __future__ import annotations

import asyncio


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


async def test_track_events_requires_admin(db, api, admin_headers):
    """The live board stream is admin-only: header or `?admin_key=`, nothing else."""
    auth = await _create_client(api, admin_headers)

    response = await api.get("/api/v1/track/events", headers=auth)
    assert response.status_code == 403

    response = await api.get("/api/v1/track/events")
    assert response.status_code == 403

    response = await api.get("/api/v1/track/events?admin_key=wrong-key")
    assert response.status_code == 403


async def test_admin_key_query_param():
    """`?admin_key=` is accepted (browser EventSource can't set headers)."""
    import pytest
    from fastapi import HTTPException

    from app.api.deps import require_admin
    from app.core.config import get_settings

    # Explicit Nones: the function's own defaults are FastAPI Header objects.
    assert await require_admin(None, None, admin_key_query=get_settings().admin_api_key) is True
    with pytest.raises(HTTPException) as exc:
        await require_admin(None, None, admin_key_query="wrong-key")
    assert exc.value.status_code == 403


async def _never_disconnected() -> bool:
    return False


async def test_track_events_emits_board_frame_for_pipeline_movement(db, api, admin_headers):
    """A `board` frame fires when the audit watermark moves past the cursor.

    Cursor `0` (replay from the start) — deterministic: ingest first so an
    audit row exists, then the first poll must emit. The stream is driven as
    the generator it is: httpx's ASGI test transport can't consume an
    open-ended SSE response (it runs the app to completion first).
    """
    from app.api.routers import track as track_mod

    auth = await _create_client(api, admin_headers)
    response = await api.post(
        "/api/v1/items",
        json={
            "body": "Kathmandu, 17 October 2026 — SSE board frame item with "
            "enough text to be a plausible wire dispatch for the pipeline.",
            "source_key": "sse-board-1",
        },
        headers=auth,
    )
    assert response.status_code == 202, response.text

    stream = track_mod._track_board_stream(resume="0", is_disconnected=_never_disconnected)
    frame = await asyncio.wait_for(anext(stream), timeout=5)
    await stream.aclose()

    assert "event: board" in frame
    assert "audit_count" in frame
    assert frame.startswith("id: ")


async def test_track_events_survives_poll_failure(db, monkeypatch):
    """A mid-stream DB error must end the stream cleanly — no teardown crash.

    Regression: the poll used to swallow errors without rollback while the
    request-scoped session was still open, so request teardown hit
    ``PendingRollbackError`` ("Exception in ASGI application" in prod logs).
    """
    from app.api.routers import track as track_mod

    calls = {"n": 0}
    real = track_mod._audit_count

    async def flaky(session):
        calls["n"] += 1
        if calls["n"] > 1:  # cursor init succeeds; the first live poll fails
            raise RuntimeError("simulated poll failure")
        return await real(session)

    monkeypatch.setattr(track_mod, "_audit_count", flaky)

    stream = track_mod._track_board_stream(resume=None, is_disconnected=_never_disconnected)
    frames = [frame async for frame in stream]  # ends when the failed poll breaks

    assert frames == []  # no frames, no exception — client will reconnect
