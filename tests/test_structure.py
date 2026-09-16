from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from pagetrace.documents import MediaType, ingest_document
from pagetrace.extraction import extract_document_text
from pagetrace.ocr import ocr_document
from pagetrace.ocr.engine import OcrEngineResult
from pagetrace.ocr.rendering import RenderedPage
from pagetrace.structure import (
    BoundingBox,
    StructureConfig,
    StructuredTable,
    StructureLimitError,
    StructureLimits,
    StructureProcessingError,
    StructureProcessorDescriptor,
    TextSpanSource,
    load_structured_document,
    structure_document,
)
from pagetrace.structure.layout import PdfPageLayout, PositionedTable, PositionedWord
from tests.conftest import ImageFactory, TextPdfFactory
from tests.test_ocr import _descriptor, _install_fake_runtime


class _ReplayEngine:
    def __init__(self, result: OcrEngineResult) -> None:
        self._result = result

    def recognize(self, _image: object) -> OcrEngineResult:
        return self._result


def test_image_ocr_geometry_becomes_positioned_structure(
    tmp_path: Path,
    image_factory: ImageFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "store"
    source = image_factory(tmp_path / "page.png", image_format="PNG", size=(100, 80))
    manifest = ingest_document(source, store=store)
    text_artifact = extract_document_text(manifest.document_id, store=store)
    _install_fake_runtime(
        monkeypatch,
        manifest.media_type,
        (OcrEngineResult(("PageTrace",), (0.9,)),),
    )
    ocr_artifact = ocr_document(manifest.document_id, text_artifact.artifact_id, store=store)

    replay = OcrEngineResult(
        lines=("PageTrace",),
        confidences=(0.9,),
        boxes=(((10, 10), (90, 10), (90, 70), (10, 70)),),
    )
    monkeypatch.setattr(
        "pagetrace.structure.processing.current_ocr_processor_descriptor",
        lambda _media_type: _descriptor(MediaType.PNG),
    )
    monkeypatch.setattr(
        "pagetrace.structure.processing.create_ocr_engine",
        lambda _configuration: _ReplayEngine(replay),
    )

    artifact = structure_document(
        manifest.document_id,
        text_artifact.artifact_id,
        ocr_artifact.artifact_id,
        store=store,
    )
    loaded = load_structured_document(
        artifact.artifact_id,
        document_id=manifest.document_id,
        store=store,
    )

    assert loaded == artifact
    assert artifact.span_count == 1
    assert artifact.pages[0].spans[0].source is TextSpanSource.OCR_LINE
    assert artifact.pages[0].spans[0].bounding_box == BoundingBox(10, 10, 90, 70)
    assert artifact.pages[0].dimension_unit.value == "pixels"


def test_pdf_words_and_tables_are_structured_without_ocr_replay(
    tmp_path: Path,
    text_pdf_factory: TextPdfFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "store"
    source = text_pdf_factory(tmp_path / "page.pdf", ["Enough embedded text"])
    manifest = ingest_document(source, store=store)
    text_artifact = extract_document_text(manifest.document_id, store=store)
    _install_fake_runtime(monkeypatch, manifest.media_type, ())
    ocr_artifact = ocr_document(manifest.document_id, text_artifact.artifact_id, store=store)

    table_box = BoundingBox(10, 120, 190, 180)
    table = PositionedTable(
        bounding_box=table_box,
        row_count=1,
        column_count=1,
        cells=(),
    )
    layout = PdfPageLayout(
        width=200,
        height=200,
        words=(PositionedWord("Enough", BoundingBox(10, 90, 55, 105)),),
        tables=(table,),
    )
    monkeypatch.setattr(
        "pagetrace.structure.processing.current_structure_processor_descriptor",
        lambda _media_type: _structure_descriptor(),
    )
    monkeypatch.setattr(
        "pagetrace.structure.processing.extract_pdf_layout",
        lambda _bytes, _manifest, _configuration: (layout,),
    )

    artifact = structure_document(
        manifest.document_id,
        text_artifact.artifact_id,
        ocr_artifact.artifact_id,
        store=store,
    )

    assert artifact.pages[0].spans[0].source is TextSpanSource.EMBEDDED_WORD
    assert artifact.pages[0].spans[0].text == "Enough"
    assert isinstance(artifact.pages[0].tables[0], StructuredTable)
    assert artifact.table_count == 1


def test_combined_span_limit_rejects_without_partial_artifact(
    tmp_path: Path,
    image_factory: ImageFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "store"
    source = image_factory(tmp_path / "page.png", image_format="PNG", size=(100, 80))
    manifest = ingest_document(source, store=store)
    text_artifact = extract_document_text(manifest.document_id, store=store)
    _install_fake_runtime(
        monkeypatch,
        manifest.media_type,
        (OcrEngineResult(("one", "two"), (0.9, 0.9)),),
    )
    ocr_artifact = ocr_document(manifest.document_id, text_artifact.artifact_id, store=store)
    replay = OcrEngineResult(
        ("one", "two"),
        (0.9, 0.9),
        (
            ((1, 1), (10, 1), (10, 10), (1, 10)),
            ((20, 1), (30, 1), (30, 10), (20, 10)),
        ),
    )
    monkeypatch.setattr(
        "pagetrace.structure.processing.current_ocr_processor_descriptor",
        lambda _media_type: _descriptor(MediaType.PNG),
    )
    monkeypatch.setattr(
        "pagetrace.structure.processing.create_ocr_engine",
        lambda _configuration: _ReplayEngine(replay),
    )
    configuration = StructureConfig(limits=StructureLimits(max_spans_per_page=1))

    with pytest.raises(StructureLimitError, match="span limit"):
        structure_document(
            manifest.document_id,
            text_artifact.artifact_id,
            ocr_artifact.artifact_id,
            store=store,
            configuration=configuration,
        )

    assert not (store / "documents" / manifest.document_id / "artifacts" / "structure").exists()


def test_ocr_geometry_replay_requires_exact_render_dimensions(
    tmp_path: Path,
    image_factory: ImageFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "store"
    source = image_factory(tmp_path / "page.png", image_format="PNG", size=(100, 80))
    manifest = ingest_document(source, store=store)
    text_artifact = extract_document_text(manifest.document_id, store=store)
    _install_fake_runtime(
        monkeypatch,
        manifest.media_type,
        (OcrEngineResult(("PageTrace",), (0.9,)),),
    )
    ocr_artifact = ocr_document(manifest.document_id, text_artifact.artifact_id, store=store)
    replay = OcrEngineResult(
        ("PageTrace",),
        (0.9,),
        (((10, 10), (90, 10), (90, 70), (10, 70)),),
    )
    monkeypatch.setattr(
        "pagetrace.structure.processing.current_ocr_processor_descriptor",
        lambda _media_type: _descriptor(MediaType.PNG),
    )
    monkeypatch.setattr(
        "pagetrace.structure.processing.create_ocr_engine",
        lambda _configuration: _ReplayEngine(replay),
    )
    monkeypatch.setattr(
        "pagetrace.structure.processing.render_selected_pages",
        lambda *_args, **_kwargs: iter((RenderedPage(1, Image.new("RGB", (99, 80))),)),
    )

    with pytest.raises(StructureProcessingError, match="dimensions"):
        structure_document(
            manifest.document_id,
            text_artifact.artifact_id,
            ocr_artifact.artifact_id,
            store=store,
        )

    tiny_geometry = OcrEngineResult(
        ("PageTrace",),
        (0.9,),
        (((0.1, 0.1), (0.2, 0.1), (0.2, 0.2), (0.1, 0.2)),),
    )
    monkeypatch.setattr(
        "pagetrace.structure.processing.create_ocr_engine",
        lambda _configuration: _ReplayEngine(tiny_geometry),
    )
    monkeypatch.setattr(
        "pagetrace.structure.processing.render_selected_pages",
        lambda *_args, **_kwargs: iter((RenderedPage(1, Image.new("RGB", (100, 80))),)),
    )
    with pytest.raises(StructureProcessingError, match="geometry is invalid"):
        structure_document(
            manifest.document_id,
            text_artifact.artifact_id,
            ocr_artifact.artifact_id,
            store=store,
            configuration=StructureConfig(coordinate_precision=0),
        )


def _structure_descriptor() -> StructureProcessorDescriptor:
    return StructureProcessorDescriptor(
        name="pagetrace-structured-document",
        version="1",
        pdf_layout_backend_name="pdfplumber",
        pdf_layout_backend_version="0.11.9",
    )
