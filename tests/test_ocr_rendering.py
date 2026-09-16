from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

import pagetrace.ocr.rendering as rendering
from pagetrace.documents import ingest_document
from pagetrace.ocr import (
    OcrConfig,
    OcrDependencyError,
    OcrLimitError,
    OcrLimits,
    OcrProcessingError,
)
from pagetrace.ocr.rendering import render_selected_pages
from tests.conftest import ImageFactory, PdfFactory


def test_real_image_page_is_loaded_without_resampling(
    tmp_path: Path, image_factory: ImageFactory
) -> None:
    source = image_factory(tmp_path / "page.png", image_format="PNG", size=(13, 7))
    manifest = ingest_document(source, store=tmp_path / "store")

    rendered = list(render_selected_pages(source.read_bytes(), manifest, (1,), OcrConfig()))

    assert [(page.page_number, page.image.mode, page.image.size) for page in rendered] == [
        (1, "RGB", (13, 7))
    ]


def test_real_pdf_page_is_rendered_at_configured_dpi(
    tmp_path: Path, pdf_factory: PdfFactory
) -> None:
    source = pdf_factory(tmp_path / "page.pdf", pages=1)
    manifest = ingest_document(source, store=tmp_path / "store")

    rendered = list(
        render_selected_pages(source.read_bytes(), manifest, (1,), OcrConfig(render_dpi=72))
    )

    assert rendered[0].page_number == 1
    assert rendered[0].image.mode == "RGB"
    assert rendered[0].image.size == (72, 144)


def test_empty_selection_does_not_load_renderer(
    tmp_path: Path, pdf_factory: PdfFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = pdf_factory(tmp_path / "page.pdf")
    manifest = ingest_document(source, store=tmp_path / "store")
    monkeypatch.setattr(
        "pagetrace.ocr.rendering.importlib.import_module",
        lambda _name: pytest.fail("renderer must stay lazy"),
    )

    assert list(render_selected_pages(source.read_bytes(), manifest, (), OcrConfig())) == []


@pytest.mark.parametrize("selection", [(1, 1), (2, 1), (0,), (2,)])
def test_invalid_page_selection_is_rejected_before_rendering(
    tmp_path: Path,
    image_factory: ImageFactory,
    selection: tuple[int, ...],
) -> None:
    source = image_factory(tmp_path / "page.png", image_format="PNG")
    manifest = ingest_document(source, store=tmp_path / "store")

    with pytest.raises(OcrProcessingError, match="selected OCR"):
        list(render_selected_pages(source.read_bytes(), manifest, selection, OcrConfig()))


def test_preflight_enforces_page_and_document_pixel_limits(
    tmp_path: Path, pdf_factory: PdfFactory
) -> None:
    source = pdf_factory(tmp_path / "pages.pdf", pages=2)
    manifest = ingest_document(source, store=tmp_path / "store")

    with pytest.raises(OcrLimitError, match="page 1"):
        list(
            render_selected_pages(
                source.read_bytes(),
                manifest,
                (1,),
                OcrConfig(
                    render_dpi=72,
                    limits=OcrLimits(max_pixels_per_page=10_367),
                ),
            )
        )

    with pytest.raises(OcrLimitError, match="document OCR limit"):
        list(
            render_selected_pages(
                source.read_bytes(),
                manifest,
                (1, 2),
                OcrConfig(
                    render_dpi=72,
                    limits=OcrLimits(max_pixels_per_document=20_735),
                ),
            )
        )


def test_page_count_limit_is_enforced_in_renderer_preflight(
    tmp_path: Path, pdf_factory: PdfFactory
) -> None:
    source = pdf_factory(tmp_path / "pages.pdf", pages=2)
    manifest = ingest_document(source, store=tmp_path / "store")

    with pytest.raises(OcrLimitError, match="1-page"):
        list(
            render_selected_pages(
                source.read_bytes(),
                manifest,
                (1, 2),
                OcrConfig(limits=OcrLimits(max_pages_per_document=1)),
            )
        )


def test_pdf_renderer_dependency_and_decode_failures_are_domain_errors(
    tmp_path: Path, pdf_factory: PdfFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = pdf_factory(tmp_path / "page.pdf")
    manifest = ingest_document(source, store=tmp_path / "store")

    def missing(_name: str) -> object:
        raise ImportError

    monkeypatch.setattr("pagetrace.ocr.rendering.importlib.import_module", missing)
    with pytest.raises(OcrDependencyError, match="install PageTrace"):
        list(render_selected_pages(source.read_bytes(), manifest, (1,), OcrConfig()))

    monkeypatch.undo()
    with pytest.raises(OcrProcessingError, match="could not render"):
        list(render_selected_pages(b"not a PDF", manifest, (1,), OcrConfig()))


def test_pdf_renderer_checks_verified_page_count(tmp_path: Path, pdf_factory: PdfFactory) -> None:
    one_page = pdf_factory(tmp_path / "one.pdf", pages=1)
    two_pages = pdf_factory(tmp_path / "two.pdf", pages=2)
    manifest = ingest_document(two_pages, store=tmp_path / "store")

    with pytest.raises(OcrProcessingError, match="page count"):
        list(render_selected_pages(one_page.read_bytes(), manifest, (1,), OcrConfig()))


def test_image_decode_validates_manifest_and_input_bytes(
    tmp_path: Path, image_factory: ImageFactory
) -> None:
    expected = image_factory(tmp_path / "expected.png", image_format="PNG", size=(4, 3))
    different = image_factory(tmp_path / "different.png", image_format="PNG", size=(5, 3))
    manifest = ingest_document(expected, store=tmp_path / "store")

    with pytest.raises(OcrProcessingError, match="metadata"):
        list(render_selected_pages(different.read_bytes(), manifest, (1,), OcrConfig()))
    with pytest.raises(OcrProcessingError, match="could not decode"):
        list(render_selected_pages(b"not an image", manifest, (1,), OcrConfig()))


def test_image_decode_rejects_unexpected_multiple_frames(
    tmp_path: Path, image_factory: ImageFactory
) -> None:
    source = image_factory(tmp_path / "expected.png", image_format="PNG", size=(4, 3))
    manifest = ingest_document(source, store=tmp_path / "store")
    first = Image.new("RGB", (4, 3), "white")
    second = Image.new("RGB", (4, 3), "black")
    buffer = BytesIO()
    first.save(buffer, format="PNG", save_all=True, append_images=[second], duration=100)

    with pytest.raises(OcrProcessingError, match="multiple frames"):
        list(render_selected_pages(buffer.getvalue(), manifest, (1,), OcrConfig()))


def test_actual_pixel_guard_rechecks_page_and_document_limits() -> None:
    page_limited = OcrConfig(limits=OcrLimits(max_pixels_per_page=3))
    with pytest.raises(OcrLimitError, match="rendered output"):
        rendering._enforce_actual_pixels(2, 2, 1, 0, page_limited)

    document_limited = OcrConfig(limits=OcrLimits(max_pixels_per_document=5))
    with pytest.raises(OcrLimitError, match="document OCR limit"):
        rendering._enforce_actual_pixels(2, 2, 2, 4, document_limited)


def test_planned_pdf_dimensions_account_for_rotation_and_round_up() -> None:
    assert rendering._planned_pdf_dimensions(72.1, 36.1, 0, 72) == (73, 37)
    assert rendering._planned_pdf_dimensions(72, 36, 90, 72) == (36, 72)
