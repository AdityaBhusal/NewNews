"""Delivery SSE stream (`GET /api/v1/events`): stream-owned session safety.

The stream owns its DB session (commits per poll, rolls back on failure).
Regression: it used to share a request-scoped session — a mid-stream DB error
left the transaction invalid and request teardown crashed with
``PendingRollbackError`` ("Exception in ASGI application" in prod logs), which
killed the app's live view until a manual reload. The stream is driven as the
generator it is: httpx's ASGI test transport can't consume an open-ended SSE
response (it runs the app to completion first).
"""

from __future__ import annotations


async def _never_disconnected() -> bool:
    return False


async def test_events_requires_client_key(db, api):
    response = await api.get("/api/v1/events")
    assert response.status_code == 401


async def test_events_stream_survives_poll_failure(db, monkeypatch):
    """A mid-stream DB error must end the stream cleanly — no teardown crash."""
    from app.api.routers import events as events_mod

    async def boom(session, *, client_id: str, cursor: int):
        raise RuntimeError("simulated poll failure")

    monkeypatch.setattr(events_mod, "_pending_deliveries", boom)

    stream = events_mod._delivery_stream(
        client_id="unused", cursor=0, is_disconnected=_never_disconnected
    )
    frames = [frame async for frame in stream]  # ends when the failed poll breaks

    assert frames == []  # no frames, no exception — client will reconnect
