from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from PIL import Image

from pagetrace.documents import DocumentManifest, MediaType, ingest_document
from pagetrace.extraction import TextExtractionArtifact, extract_document_text
from pagetrace.ocr import (
    OcrConfig,
    OcrIntegrityError,
    OcrLimitError,
    OcrLimits,
    OcrPageStatus,
    OcrProcessorDescriptor,
    OcrRoutingPolicy,
    load_ocr_artifact,
    ocr_document,
)
from pagetrace.ocr.engine import OcrEngineResult
from pagetrace.ocr.rendering import RenderedPage
from tests.conftest import ImageFactory, TextPdfFactory


class _FakeEngine:
    def __init__(self, results: tuple[OcrEngineResult, ...]) -> None:
        self._results = iter(results)

    def recognize(self, _image: Image.Image) -> OcrEngineResult:
        return next(self._results)


def test_image_candidate_is_ocrd_and_persisted_with_provenance(
    tmp_path: Path,
    image_factory: ImageFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(
        image_factory(tmp_path / "page.png", image_format="PNG"), store=store
    )
    text_artifact = extract_document_text(manifest.document_id, store=store)
    _install_fake_runtime(
        monkeypatch,
        manifest.media_type,
        (OcrEngineResult(("PageTrace", "OCR"), (0.9, 0.8)),),
    )

    artifact = ocr_document(
        manifest.document_id,
        text_artifact.artifact_id,
        store=store,
    )
    loaded = load_ocr_artifact(
        artifact.artifact_id,
        document_id=manifest.document_id,
        store=store,
    )

    assert loaded == artifact
    assert artifact.source_text_artifact_id == text_artifact.artifact_id
    assert artifact.source_text_content_fingerprint == text_artifact.content_fingerprint
    assert artifact.selected_page_count == 1
    assert artifact.pages[0].status is OcrPageStatus.OCR_TEXT
    assert artifact.pages[0].text == "PageTrace\nOCR"
    assert artifact.pages[0].mean_confidence == 0.85
    assert _artifact_path(store, manifest.document_id, artifact.artifact_id).is_file()


def test_empty_engine_output_is_recorded_without_fabricated_text(
    tmp_path: Path,
    image_factory: ImageFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manifest, text_artifact = _stored_image(tmp_path, image_factory)
    _install_fake_runtime(
        monkeypatch,
        manifest.media_type,
        (OcrEngineResult((), ()),),
    )

    artifact = ocr_document(manifest.document_id, text_artifact.artifact_id, store=store)

    page = artifact.pages[0]
    assert page.status is OcrPageStatus.OCR_NO_TEXT
    assert page.text is None
    assert page.character_count == 0
    assert page.mean_confidence is None


def test_default_policy_ocrs_candidate_and_sparse_pages_only(
    tmp_path: Path,
    text_pdf_factory: TextPdfFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(
        text_pdf_factory(tmp_path / "pages.pdf", ["Enough embedded text", "x", ""]),
        store=store,
    )
    text_artifact = extract_document_text(manifest.document_id, store=store)
    _install_fake_runtime(
        monkeypatch,
        manifest.media_type,
        (
            OcrEngineResult(("sparse OCR",), (0.8,)),
            OcrEngineResult(("blank OCR",), (0.9,)),
        ),
    )

    artifact = ocr_document(manifest.document_id, text_artifact.artifact_id, store=store)

    assert artifact.selected_page_count == 2
    assert [page.status for page in artifact.pages] == [
        OcrPageStatus.NOT_SELECTED,
        OcrPageStatus.OCR_TEXT,
        OcrPageStatus.OCR_TEXT,
    ]
    assert artifact.pages[0].rendered_width_pixels is None


def test_candidates_only_policy_excludes_sparse_embedded_text(
    tmp_path: Path,
    text_pdf_factory: TextPdfFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(text_pdf_factory(tmp_path / "pages.pdf", ["x", ""]), store=store)
    text_artifact = extract_document_text(manifest.document_id, store=store)
    _install_fake_runtime(
        monkeypatch,
        manifest.media_type,
        (OcrEngineResult(("candidate",), (0.9,)),),
    )

    artifact = ocr_document(
        manifest.document_id,
        text_artifact.artifact_id,
        store=store,
        configuration=OcrConfig(routing_policy=OcrRoutingPolicy.CANDIDATES_ONLY),
    )

    assert artifact.selected_page_count == 1
    assert artifact.pages[0].status is OcrPageStatus.NOT_SELECTED
    assert artifact.pages[1].status is OcrPageStatus.OCR_TEXT


def test_page_selection_limit_fails_before_engine_or_artifact_creation(
    tmp_path: Path,
    text_pdf_factory: TextPdfFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(text_pdf_factory(tmp_path / "pages.pdf", ["", ""]), store=store)
    text_artifact = extract_document_text(manifest.document_id, store=store)
    monkeypatch.setattr(
        "pagetrace.ocr.processing.create_ocr_engine",
        lambda _configuration: pytest.fail("engine must not initialize"),
    )
    configuration = OcrConfig(limits=OcrLimits(max_pages_per_document=1))

    with pytest.raises(OcrLimitError, match="1-page"):
        ocr_document(
            manifest.document_id,
            text_artifact.artifact_id,
            store=store,
            configuration=configuration,
        )

    assert not (store / "documents" / manifest.document_id / "artifacts" / "ocr").exists()


def test_character_limit_rejects_without_truncation_or_partial_artifact(
    tmp_path: Path,
    image_factory: ImageFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manifest, text_artifact = _stored_image(tmp_path, image_factory)
    output = "123456"
    _install_fake_runtime(
        monkeypatch,
        manifest.media_type,
        (OcrEngineResult((output,), (0.9,)),),
    )
    configuration = OcrConfig(
        limits=OcrLimits(max_characters_per_page=5, max_characters_per_document=10)
    )

    with pytest.raises(OcrLimitError, match="5-character per-page"):
        ocr_document(
            manifest.document_id,
            text_artifact.artifact_id,
            store=store,
            configuration=configuration,
        )

    assert output == "123456"
    assert not (store / "documents" / manifest.document_id / "artifacts" / "ocr").exists()


def test_document_character_limit_is_incremental(
    tmp_path: Path,
    text_pdf_factory: TextPdfFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(text_pdf_factory(tmp_path / "pages.pdf", ["", ""]), store=store)
    text_artifact = extract_document_text(manifest.document_id, store=store)
    _install_fake_runtime(
        monkeypatch,
        manifest.media_type,
        (
            OcrEngineResult(("1234",), (0.9,)),
            OcrEngineResult(("5678",), (0.9,)),
        ),
    )
    configuration = OcrConfig(
        limits=OcrLimits(max_characters_per_page=4, max_characters_per_document=7)
    )

    with pytest.raises(OcrLimitError, match="at page 2"):
        ocr_document(
            manifest.document_id,
            text_artifact.artifact_id,
            store=store,
            configuration=configuration,
        )


def test_configuration_changes_ocr_artifact_identity(
    tmp_path: Path,
    image_factory: ImageFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manifest, text_artifact = _stored_image(tmp_path, image_factory)
    _install_fake_runtime(
        monkeypatch,
        manifest.media_type,
        (OcrEngineResult(("same",), (0.9,)),),
    )
    first = ocr_document(manifest.document_id, text_artifact.artifact_id, store=store)
    _install_fake_runtime(
        monkeypatch,
        manifest.media_type,
        (OcrEngineResult(("same",), (0.9,)),),
    )
    second = ocr_document(
        manifest.document_id,
        text_artifact.artifact_id,
        store=store,
        configuration=OcrConfig(render_dpi=201),
    )

    assert first.artifact_id != second.artifact_id


def test_repeated_ocr_is_idempotent(
    tmp_path: Path,
    image_factory: ImageFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manifest, text_artifact = _stored_image(tmp_path, image_factory)
    _install_fake_runtime(
        monkeypatch,
        manifest.media_type,
        (
            OcrEngineResult(("stable",), (0.9,)),
            OcrEngineResult(("stable",), (0.9,)),
        ),
    )

    first = ocr_document(manifest.document_id, text_artifact.artifact_id, store=store)
    path = _artifact_path(store, manifest.document_id, first.artifact_id)
    original = path.read_bytes()
    second = ocr_document(manifest.document_id, text_artifact.artifact_id, store=store)

    assert second == first
    assert path.read_bytes() == original


def test_corrupted_ocr_artifact_is_rejected(
    tmp_path: Path,
    image_factory: ImageFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manifest, text_artifact = _stored_image(tmp_path, image_factory)
    _install_fake_runtime(
        monkeypatch,
        manifest.media_type,
        (OcrEngineResult(("trusted",), (0.9,)),),
    )
    artifact = ocr_document(manifest.document_id, text_artifact.artifact_id, store=store)
    path = _artifact_path(store, manifest.document_id, artifact.artifact_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["pages"][0]["text"] = "tampered"
    payload["pages"][0]["character_count"] = 8
    payload["pages"][0]["non_whitespace_character_count"] = 8
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(OcrIntegrityError, match="content_fingerprint"):
        load_ocr_artifact(
            artifact.artifact_id,
            document_id=manifest.document_id,
            store=store,
        )


@pytest.mark.parametrize("artifact_id", ["../escape", "..\\escape", "ocr-not-valid", ""])
def test_unsafe_ocr_artifact_id_cannot_escape_store(tmp_path: Path, artifact_id: str) -> None:
    with pytest.raises(OcrIntegrityError, match="artifact_id"):
        load_ocr_artifact(
            artifact_id,
            document_id=f"sha256-{'0' * 64}",
            store=tmp_path / "store",
        )


def _install_fake_runtime(
    monkeypatch: pytest.MonkeyPatch,
    media_type: MediaType,
    results: tuple[OcrEngineResult, ...],
) -> None:
    monkeypatch.setattr(
        "pagetrace.ocr.processing.current_ocr_processor_descriptor",
        lambda _media_type: _descriptor(media_type),
    )
    engine = _FakeEngine(results)
    monkeypatch.setattr("pagetrace.ocr.processing.create_ocr_engine", lambda _configuration: engine)

    def fake_render(
        _source_bytes: bytes,
        _manifest: object,
        selected_page_numbers: tuple[int, ...],
        _configuration: OcrConfig,
    ) -> Iterator[RenderedPage]:
        for page_number in selected_page_numbers:
            yield RenderedPage(page_number, Image.new("RGB", (100, 80), "white"))

    monkeypatch.setattr("pagetrace.ocr.processing.render_selected_pages", fake_render)


def _descriptor(media_type: MediaType) -> OcrProcessorDescriptor:
    is_pdf = media_type is MediaType.PDF
    return OcrProcessorDescriptor(
        name="pagetrace-routed-ocr",
        version="1",
        engine_name="rapidocr",
        engine_version="3.9.2",
        inference_backend_name="onnxruntime",
        inference_backend_version="1.30.0",
        inference_profile="cpu-single-thread",
        model_profile="pp-ocrv6-small-ch-cls-v4-mobile",
        model_fingerprint="7" * 64,
        pdf_renderer_name="pypdfium2" if is_pdf else None,
        pdf_renderer_version="5.13.0" if is_pdf else None,
    )


def _stored_image(
    tmp_path: Path, image_factory: ImageFactory
) -> tuple[Path, DocumentManifest, TextExtractionArtifact]:
    store = tmp_path / "store"
    manifest = ingest_document(
        image_factory(tmp_path / "page.png", image_format="PNG"), store=store
    )
    text_artifact = extract_document_text(manifest.document_id, store=store)
    return store, manifest, text_artifact


def _artifact_path(store: Path, document_id: str, artifact_id: str) -> Path:
    return store / "documents" / document_id / "artifacts" / "ocr" / f"{artifact_id}.json"
