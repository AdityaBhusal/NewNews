"""Stage: media content extraction (FIRST_STAGE of the pipeline).

Runs before `extract` so language detection, dedupe and the AI assessment all see
the *extracted* content as part of the item body:

    extract_media -> extract -> dedupe -> validate -> enrich -> match

Per asset (`media_assets.extraction_status`: pending -> extracted | error):

- **document (PDF)**: embedded text via pypdf; if a page yields almost no text —
  or the layer is *mojibake* (Nepali typeset in Preeti/Krutidev-style custom
  fonts extracts as ASCII like `tl/sfnfO{` = नेपाल, code-punctuation-dense) —
  the file is treated as a scan: pages are rasterized (pypdfium2, no system
  deps) and OCRed with Tesseract (`nep` + `eng` baked into the image), because
  the rendered glyphs are ground truth.
- **image**: Tesseract OCR (`MEDIA_OCR_LANGUAGES`, default `nep+eng`).
- **audio**: Groq Whisper transcription (requires `AI_PROVIDER=groq`).
- **video**: ffmpeg (baked into the image) pulls the audio track -> Whisper.
- **text**: nothing to do (the body IS the text).

Extracted text is stored on the asset (`extracted_text`, for provenance) *and*
appended to `item.body` under a `[..., extracted text]` marker so every later
stage reads one canonical text. The append happens exactly once — only when the
asset flips from pending to extracted — so the stage is safely re-runnable
(invariant: stages must be idempotent).

Failures never kill the item: the asset records `extraction_status='error'` +
the reason, and the pipeline continues with whatever text exists.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models import MediaAsset, NewsItem
from app.pipeline.ai.base import AIProvider
from app.pipeline.audit import record_audit

log = get_logger("newnews.media_extract")

KIND_DOCUMENT = "document"
KIND_IMAGE = "image"
KIND_AUDIO = "audio"
KIND_VIDEO = "video"
KIND_TEXT = "text"

# PDF pages rasterized for OCR (dpi = 72 * scale)
OCR_RENDER_SCALE = 300 / 72


def _read_pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _ocr_pil(image) -> str:
    import pytesseract

    settings = get_settings()
    return pytesseract.image_to_string(image, lang=settings.media_ocr_languages)


def _ocr_pdf(path: Path) -> str:
    """Render scanned pages to images and OCR them (no poppler needed)."""
    import pypdfium2 as pdfium

    settings = get_settings()
    document = pdfium.PdfDocument(str(path))
    chunks: list[str] = []
    try:
        for index in range(min(len(document), settings.media_pdf_max_pages)):
            page = document[index]
            bitmap = page.render(scale=OCR_RENDER_SCALE)
            chunks.append(_ocr_pil(bitmap.to_pil()))
    finally:
        document.close()
    return "\n".join(chunks)


# Characters dense in custom-font mojibake but rare in running prose.
_MOJIBAKE_HEAVY = frozenset(r"/\{}[];|~")


def is_mojibake(text: str) -> bool:
    """True when a text layer is a custom-font artifact, not usable prose.

    Nepali typeset in Preeti/Krutidev-style fonts (or subset fonts with broken
    glyph→Unicode maps) extracts as ASCII like `tl/sfnfO{` = नेपाल — or as
    mangled Devanagari (`कायाालय`) — always accompanied by a heavy density of
    code punctuation (`/ \\ { } [ ] ; | ~`): ~12% in a real Gorkhapatra layer
    vs <1% in English prose and ~0% in genuine Unicode Nepali. OCR of the
    rendered pages is ground truth for such files, so we hand off to it.
    """
    sample = text[:20_000]
    if len(sample.strip()) < 40:
        return False
    density = sum(ch in _MOJIBAKE_HEAVY for ch in sample) / len(sample)
    return density > 0.03


def extract_document(path: Path) -> str:
    """PDF text; OCR when the layer is missing *or* is custom-font mojibake."""
    settings = get_settings()
    text = _read_pdf_text(path)
    if len(text.strip()) >= settings.media_pdf_text_min_chars and not is_mojibake(text):
        return text.strip()
    try:
        ocr_text = _ocr_pdf(path)
    except Exception:  # noqa: BLE001 — no tesseract/render failure: keep the layer
        return text.strip()
    return (ocr_text or text).strip()


def extract_image(path: Path) -> str:
    from PIL import Image

    with Image.open(path) as image:
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        return _ocr_pil(image).strip()


async def extract_video(path: Path) -> str:
    """Pull a 16 kHz mono wav of the audio track, then transcribe it."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH (baked into the Docker image)")
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", str(wav)],
            check=True,
            capture_output=True,
            timeout=300,
        )
        return await _transcribe_file(wav)


async def extract_audio(path: Path) -> str:
    return await _transcribe_file(path)


async def _transcribe_file(path: Path) -> str:
    """Whisper via the active provider; raises if it can't transcribe."""
    from app.pipeline.ai.factory import get_provider

    provider = get_provider()
    transcribe = getattr(provider, "transcribe", None)
    if transcribe is None:
        raise RuntimeError(
            f"provider {provider.name!r} cannot transcribe audio "
            "(set AI_PROVIDER=groq)"
        )
    text = await transcribe(str(path))
    return text.strip()


async def extract_asset(asset: MediaAsset) -> tuple[str, str]:
    """Dispatch one asset -> (new_status, extracted_text). Never raises."""
    if asset.kind == KIND_TEXT:
        return "extracted", ""
    path = Path(asset.uri)
    if not path.is_file():
        return "error", f"file not found: {asset.uri}"
    try:
        if asset.kind == KIND_DOCUMENT:
            text = extract_document(path)
        elif asset.kind == KIND_IMAGE:
            text = extract_image(path)
        elif asset.kind == KIND_AUDIO:
            text = await extract_audio(path)
        elif asset.kind == KIND_VIDEO:
            text = await extract_video(path)
        else:
            return "error", f"unknown media kind: {asset.kind!r}"
        return "extracted", text.strip()
    except Exception as exc:  # noqa: BLE001 — a bad asset must not kill the item
        log.warning("media extraction failed", extra={"item_id": asset.item_id, "error": str(exc)})
        return "error", f"{type(exc).__name__}: {exc}"


async def run(session: AsyncSession, item: NewsItem, provider: AIProvider) -> str | None:
    assets = (
        await session.scalars(
            select(MediaAsset)
            .where(MediaAsset.item_id == item.id, MediaAsset.extraction_status == "pending")
            .order_by(MediaAsset.created_at)
        )
    ).all()

    extracted: list[dict] = []
    errors: list[dict] = []
    appended: list[str] = []

    for asset in assets:
        status, text = await extract_asset(asset)
        asset.extraction_status = status
        if status == "error":
            asset.error = text
            errors.append({"asset_id": asset.id, "kind": asset.kind, "error": text[:300]})
            continue
        asset.extracted_text = text or None
        asset.error = None
        if text:
            label = asset.filename or asset.kind
            item.body += f"\n\n[{label} — extracted text]\n{text}"
            appended.append(label)
        extracted.append({"asset_id": asset.id, "kind": asset.kind, "chars": len(text)})

    await record_audit(
        session,
        item,
        stage="extract_media",
        event_type="media_extracted",
        detail={"extracted": extracted, "errors": errors, "appended_to_body": appended},
    )
    return "extract"
