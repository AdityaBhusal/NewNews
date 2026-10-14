"""Media upload API: POST /api/v1/items/{id}/media (multipart file).

Attaches a real file to an item **before the pipeline has started processing it**
(item status must be `received`), so the `extract_media` first stage picks it up
on its normal run: OCR/Whisper/PDF text lands in the item body before dedupe and
the AI assessment see it.

Lifecycle / failure modes (documented in docs/requirements.md FR-15):

- `201` — asset stored under MEDIA_ROOT/{item_id}/, `extraction_status=pending`,
  the already-enqueued `extract_media` job will extract it.
- `409` — item already past `received` (raced the worker, or re-upload). Attach
  media immediately after the 202 from `POST /api/v1/items`; a combined
  multipart ingest lands in M5 with the mobile client.
- `413` — file larger than `MEDIA_MAX_BYTES` (default 20 MB).
- `415` — content type not recognisable as text/image/audio/video/document.

Storage on Render's free tier is **ephemeral** — files survive until the next
deploy/restart (M4 moves this to object storage; the extracted text is already
persisted in Postgres either way).
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_client
from app.api.schemas import MediaOut
from app.core.config import get_settings
from app.core.db import get_session
from app.models import Client, MediaAsset, NewsItem
from app.pipeline.audit import record_audit
from app.pipeline.states import ItemStatus

router = APIRouter(prefix="/items", tags=["media"])

_EXT_KIND: dict[str, str] = {
    ".pdf": "document",
    ".doc": "document",
    ".docx": "document",
    ".txt": "text",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".gif": "image",
    ".tif": "image",
    ".tiff": "image",
    ".bmp": "image",
    ".mp3": "audio",
    ".wav": "audio",
    ".m4a": "audio",
    ".ogg": "audio",
    ".flac": "audio",
    ".mp4": "video",
    ".mov": "video",
    ".mkv": "video",
    ".webm": "video",
}

_SAFE_SUFFIX = re.compile(r"[^a-z0-9.]")


def kind_for(content_type: str | None, filename: str | None) -> str | None:
    """Map MIME type (preferred) or extension to a media kind."""
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct.startswith("text/"):
        return "text"
    if ct.startswith("image/"):
        return "image"
    if ct.startswith("audio/"):
        return "audio"
    if ct.startswith("video/"):
        return "video"
    if ct == "application/pdf":
        return "document"
    suffix = Path(filename or "").suffix.lower()
    return _EXT_KIND.get(suffix)


def safe_suffix(filename: str | None) -> str:
    """Sanitised extension for the stored file (no traversal, bounded length)."""
    raw = Path(filename or "").suffix.lower()
    cleaned = _SAFE_SUFFIX.sub("", raw)[:16]
    return cleaned if cleaned.startswith(".") else ""


@router.post(
    "/{item_id}/media",
    status_code=status.HTTP_201_CREATED,
    response_model=MediaOut,
)
async def upload_media(
    item_id: str,
    request: Request,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    client: Client = Depends(get_current_client),  # noqa: ARG001 — auth required
) -> MediaOut:
    settings = get_settings()

    item = await session.get(NewsItem, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="item not found")
    if item.status != ItemStatus.RECEIVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"item status is {item.status!r}; media must be attached while it is "
                "'received' (attach immediately after POST /api/v1/items returns 202)"
            ),
        )

    kind = kind_for(file.content_type, file.filename)
    if kind is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"unsupported media type: {file.content_type or file.filename!r}",
        )

    # Read in chunks so an oversized upload is rejected before the disk fills.
    limit = settings.media_max_bytes
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"file exceeds MEDIA_MAX_BYTES ({limit} bytes)",
            )
        chunks.append(chunk)
    if total == 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="empty file")

    # MEDIA_ROOT/{item_id}/{uuid}{sanitised-ext} — uuid names avoid collisions
    # and any path tricks from the client-supplied filename.
    directory = Path(settings.media_root) / item_id
    directory.mkdir(parents=True, exist_ok=True)
    stored = directory / f"{uuid.uuid4().hex}{safe_suffix(file.filename)}"
    stored.write_bytes(b"".join(chunks))

    asset = MediaAsset(
        item_id=item.id,
        kind=kind,
        uri=str(stored),
        filename=(file.filename or stored.name)[:255],
        mime_type=(file.content_type or None),
        size_bytes=total,
        media_metadata={"uploaded_via": "api"},
    )
    session.add(asset)
    await record_audit(
        session,
        item,
        stage="ingest",
        event_type="media_attached",
        detail={"asset_kind": kind, "filename": asset.filename, "size_bytes": total},
    )
    await session.commit()
    await session.refresh(asset)
    return asset
