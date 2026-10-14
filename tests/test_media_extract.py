"""Unit tests: media kind dispatch, PDF text extraction, OCR fallback (W3).

OCR tests need the `tesseract` binary — present in the Docker image (and the
CI image check), so they skip on bare hosts rather than fail.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.api.routers.media import kind_for, safe_suffix
from app.pipeline.media_extract import extract_document, extract_image
from tests.conftest import make_pdf_bytes

has_tesseract = shutil.which("tesseract") is not None
ocr = pytest.mark.skipif(not has_tesseract, reason="tesseract binary not available")

PDF_TEXT = (
    "Kathmandu road budget announced for fourteen wards of the metropolitan city. "
    "The provincial government approved the plan worth two hundred fifty million rupees."
)


# --- upload MIME/extension dispatch ----------------------------------------


def test_kind_prefers_mime_type():
    assert kind_for("application/pdf", "x.png") == "document"
    assert kind_for("image/png; charset=binary", "x.bin") == "image"
    assert kind_for("audio/mpeg", None) == "audio"
    assert kind_for("video/mp4", "clip") == "video"
    assert kind_for("text/plain", "note.txt") == "text"


def test_kind_falls_back_to_extension():
    assert kind_for("application/octet-stream", "scan.PDF") == "document"
    assert kind_for("application/octet-stream", "photo.jpeg") == "image"
    assert kind_for("application/octet-stream", "clip.webm") == "video"
    assert kind_for(None, "notes.txt") == "text"
    assert kind_for("application/octet-stream", "weird.xyz") is None
    assert kind_for(None, None) is None


def test_safe_suffix_strips_path_tricks():
    assert safe_suffix("report.pdf") == ".pdf"
    assert safe_suffix("../../etc/passwd") == ""
    assert safe_suffix("a.PDF") == ".pdf"
    assert safe_suffix("x" * 50 + ".jpeg") == ".jpeg"  # basename suffix only
    assert safe_suffix(None) == ""


# --- PDF text layer ---------------------------------------------------------


def test_mojibake_detector():
    from app.pipeline.media_extract import is_mojibake

    # Real Preeti-style output from a Nepali newspaper PDF (was fed to Groq
    # as-is until this fallback existed).
    preeti = (
        "tl/sfnfO{ k|flws/ 0fn] u/ ] sf] 5 . k|flws/ 0fn] hf/ L u/ ] sf] lj1lKt "
        "cg';f/ o;af6 : yfgLo afl;Gbf, ;/ sf/ L sfof{no, : jf: Yo ;+: yf, s'6fgL"
    )
    # A real newspaper layer: mangled Devanagari mixed with Preeti-style ASCII.
    mixed = (
        "tl/sfnfO{ k|flws/ 0fn] u/ ] sf] 5 . k|flws/ 0fn] hf/ L u/ ] sf] lj1lKt "
        "cg';f/ o;af6 : yfgLo afl;Gbf, ;/ sf/ L sfof{no के न्द्रीय कायाालय, "
        "कमलपोखरी सूचना तथा प्रकाशन शाखा ;j] {x} s/ tl/sf"
    )
    english = (
        "Kathmandu, 12 March 2026 — The Kathmandu Metropolitan City announced "
        "a Rs 250 million budget for road expansion across 14 wards."
    )
    devanagari = "काठमाडौं, १२ मार्च २०२६ — नगरपालिकाले सडक विस्तारको बजेट घोषणा गर्‍यो।"

    assert is_mojibake(preeti) is True
    assert is_mojibake(mixed) is True  # genuine-looking Devanagari doesn't save it
    assert is_mojibake(english) is False  # real prose keeps its layer
    assert is_mojibake(devanagari) is False
    assert is_mojibake("") is False
    assert is_mojibake("short") is False


def test_pdf_text_layer_extracted(tmp_path: Path):
    path = tmp_path / "article.pdf"
    path.write_bytes(make_pdf_bytes(PDF_TEXT))

    text = extract_document(path)

    assert "Kathmandu road budget" in text
    assert "two hundred fifty million" in text


@ocr
def test_scanned_pdf_falls_back_to_ocr(tmp_path: Path):
    """Image-only PDF (no text layer) -> rasterize -> tesseract."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1200, 400), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=48)
    draw.text((40, 150), "ROAD BUDGET APPROVED", fill="black", font=font)
    path = tmp_path / "scan.pdf"
    image.save(path, "PDF")

    text = extract_document(path)

    assert "ROAD BUDGET" in text.upper()


@ocr
def test_image_ocr(tmp_path: Path):
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1000, 240), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=44)
    draw.text((30, 90), "Kathmandu police arrest two", fill="black", font=font)
    path = tmp_path / "screenshot.png"
    image.save(path)

    text = extract_image(path)

    assert "Kathmandu" in text
    assert "police" in text.lower()


def test_missing_file_reports_error_status(tmp_path: Path):
    from app.models import MediaAsset
    from app.pipeline.media_extract import extract_asset

    asset = MediaAsset(
        item_id="x",
        kind="document",
        uri=str(tmp_path / "gone.pdf"),
        extraction_status="pending",
    )
    import asyncio

    status, detail = asyncio.run(extract_asset(asset))
    assert status == "error"
    assert "file not found" in detail
