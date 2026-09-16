from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from pagetrace.documents import ingest_document
from pagetrace.extraction import PageTextStatus, extract_document_text
from pagetrace.ocr import OcrPageStatus, load_ocr_artifact, ocr_document


def test_scanned_pdf_runs_real_routed_ocr_end_to_end(tmp_path: Path) -> None:
    font_path = _test_font_path()
    if font_path is None:
        pytest.skip("a deterministic TrueType test font is unavailable")
    image = Image.new("RGB", (1_200, 300), "white")
    font = ImageFont.truetype(str(font_path), 96)
    ImageDraw.Draw(image).text((40, 80), "PAGETRACE 2026", font=font, fill="black")
    source = tmp_path / "scan.pdf"
    image.save(source, format="PDF", resolution=150)
    store = tmp_path / "store"

    manifest = ingest_document(source, store=store)
    text_artifact = extract_document_text(manifest.document_id, store=store)
    artifact = ocr_document(manifest.document_id, text_artifact.artifact_id, store=store)
    loaded = load_ocr_artifact(
        artifact.artifact_id,
        document_id=manifest.document_id,
        store=store,
    )

    assert text_artifact.pages[0].status is PageTextStatus.OCR_CANDIDATE
    assert loaded == artifact
    assert artifact.pages[0].status is OcrPageStatus.OCR_TEXT
    assert artifact.pages[0].text is not None
    assert "PAGETRACE" in artifact.pages[0].text
    assert "2026" in artifact.pages[0].text
    assert artifact.processor.pdf_renderer_name == "pypdfium2"


def _test_font_path() -> Path | None:
    candidates = (
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    )
    return next((path for path in candidates if path.is_file()), None)
