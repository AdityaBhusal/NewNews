"""Demo web pages: REST feed (/feed) and live SSE view (/live).

Plain static HTML (no build step, no framework) so the delivery UIs work on every
deploy target unchanged. Both pages call the public API from the browser with the
user's own client key — nothing is proxied or stored server-side.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["pages"], include_in_schema=False)

_STATIC = Path(__file__).parent.parent / "static"


def _page(name: str) -> HTMLResponse:
    return HTMLResponse((_STATIC / name).read_text(encoding="utf-8"))


@router.get("/feed", response_class=HTMLResponse)
async def feed_page() -> HTMLResponse:
    """Delivery UI #1: pull the feed over REST (`GET /api/v1/news`)."""
    return _page("feed.html")


@router.get("/live", response_class=HTMLResponse)
async def live_page() -> HTMLResponse:
    """Delivery UI #2: live push over SSE (`GET /api/v1/events`)."""
    return _page("live.html")
