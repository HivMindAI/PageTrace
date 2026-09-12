from __future__ import annotations

import json
from dataclasses import replace
from importlib.metadata import version
from pathlib import Path

import pytest
from pypdf import PageObject, PdfReader

from pagetrace.documents import MediaType, ingest_document, load_document
from pagetrace.extraction import (
    EXTRACTION_SCHEMA_VERSION,
    ExtractionMethod,
    PageTextStatus,
    TextExtractionConfig,
    extract_document_text,
    load_text_extraction,
    serialize_text_extraction,
)
from tests.conftest import ImageFactory, TextPdfFactory


def test_single_page_pdf_preserves_real_pypdf_output(
    tmp_path: Path, text_pdf_factory: TextPdfFactory
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(
        text_pdf_factory(tmp_path / "digital.pdf", ["Hello, PageTrace!"]), store=store
    )

    artifact = extract_document_text(manifest.document_id, store=store)

    stored_pdf = store / "documents" / manifest.document_id / "source.pdf"
    expected = PdfReader(stored_pdf, strict=True).pages[0].extract_text(extraction_mode="plain")
    page = artifact.pages[0]
    assert page.status is PageTextStatus.EMBEDDED_TEXT
    assert page.method is ExtractionMethod.PYPDF_EMBEDDED_TEXT
    assert page.text == expected
    assert page.character_count == len(expected)
    assert page.non_whitespace_character_count == sum(not char.isspace() for char in expected)


def test_multi_page_digital_pdf_extracts_each_page(
    tmp_path: Path, text_pdf_factory: TextPdfFactory
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(
        text_pdf_factory(tmp_path / "multi.pdf", ["First page", "Second page"]), store=store
    )

    artifact = extract_document_text(manifest.document_id, store=store)

    assert artifact.page_count == 2
    assert [page.status for page in artifact.pages] == [
        PageTextStatus.EMBEDDED_TEXT,
        PageTextStatus.EMBEDDED_TEXT,
    ]
    assert [page.page_number for page in artifact.pages] == [1, 2]
    assert "First page" in (artifact.pages[0].text or "")
    assert "Second page" in (artifact.pages[1].text or "")


def test_blank_pdf_page_is_an_ocr_candidate_without_fabricated_text(
    tmp_path: Path, text_pdf_factory: TextPdfFactory
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(text_pdf_factory(tmp_path / "scan.pdf", [None]), store=store)

    page = extract_document_text(manifest.document_id, store=store).pages[0]

    assert page.status is PageTextStatus.OCR_CANDIDATE
    assert page.method is ExtractionMethod.PYPDF_EMBEDDED_TEXT
    assert page.text is None
    assert page.character_count == 0
    assert page.non_whitespace_character_count == 0


@pytest.mark.parametrize(
    ("image_format", "suffix", "media_type"),
    [("PNG", ".png", MediaType.PNG), ("JPEG", ".jpg", MediaType.JPEG)],
)
def test_image_is_routed_without_ocr_or_reencoding(
    tmp_path: Path,
    image_factory: ImageFactory,
    image_format: str,
    suffix: str,
    media_type: MediaType,
) -> None:
    source = image_factory(tmp_path / f"image{suffix}", image_format=image_format)
    store = tmp_path / "store"
    manifest = ingest_document(source, store=store)
    stored_source = (
        store
        / "documents"
        / manifest.document_id
        / ("source.png" if media_type is MediaType.PNG else "source.jpg")
    )
    original_bytes = stored_source.read_bytes()

    page = extract_document_text(manifest.document_id, store=store).pages[0]

    assert page.status is PageTextStatus.OCR_CANDIDATE
    assert page.method is ExtractionMethod.OCR_ROUTING_ONLY
    assert page.text is None
    assert stored_source.read_bytes() == original_bytes


def test_mixed_pdf_routes_pages_independently(
    tmp_path: Path, text_pdf_factory: TextPdfFactory
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(
        text_pdf_factory(tmp_path / "mixed.pdf", ["Digital one", None, "Digital three"]),
        store=store,
    )

    artifact = extract_document_text(manifest.document_id, store=store)

    assert [page.status for page in artifact.pages] == [
        PageTextStatus.EMBEDDED_TEXT,
        PageTextStatus.OCR_CANDIDATE,
        PageTextStatus.EMBEDDED_TEXT,
    ]
    assert artifact.pages[1].text is None
    assert "Digital one" in (artifact.pages[0].text or "")
    assert "Digital three" in (artifact.pages[2].text or "")


def test_whitespace_only_extractor_output_is_not_claimed_as_text(
    tmp_path: Path,
    text_pdf_factory: TextPdfFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(
        text_pdf_factory(tmp_path / "document.pdf", ["ordinary text"]), store=store
    )
    monkeypatch.setattr(PageObject, "extract_text", lambda *_args, **_kwargs: " \n\t")

    page = extract_document_text(manifest.document_id, store=store).pages[0]

    assert page.status is PageTextStatus.OCR_CANDIDATE
    assert page.text is None


def test_extracted_unicode_punctuation_and_whitespace_are_preserved(
    tmp_path: Path,
    text_pdf_factory: TextPdfFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(
        text_pdf_factory(tmp_path / "document.pdf", ["ordinary text"]), store=store
    )
    extracted = "سلام، دنیا!\n  Café\t"
    monkeypatch.setattr(PageObject, "extract_text", lambda *_args, **_kwargs: extracted)

    page = extract_document_text(manifest.document_id, store=store).pages[0]

    assert page.status is PageTextStatus.EMBEDDED_TEXT
    assert page.text == extracted
    assert page.character_count == len(extracted)
    assert page.non_whitespace_character_count == sum(
        not character.isspace() for character in extracted
    )


def test_sparse_text_is_preserved_but_not_overstated(
    tmp_path: Path, text_pdf_factory: TextPdfFactory
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(text_pdf_factory(tmp_path / "tiny.pdf", ["A"]), store=store)

    page = extract_document_text(manifest.document_id, store=store).pages[0]

    assert page.status is PageTextStatus.SPARSE_EMBEDDED_TEXT
    assert page.text is not None
    assert page.non_whitespace_character_count == 1


def test_configuration_changes_routing_and_artifact_identity(
    tmp_path: Path, text_pdf_factory: TextPdfFactory
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(
        text_pdf_factory(tmp_path / "short.pdf", ["Short text"]), store=store
    )

    default = extract_document_text(manifest.document_id, store=store)
    strict = extract_document_text(
        manifest.document_id,
        store=store,
        configuration=TextExtractionConfig(minimum_embedded_characters=20),
    )

    assert default.artifact_id != strict.artifact_id
    assert default.pages[0].status is PageTextStatus.EMBEDDED_TEXT
    assert strict.pages[0].status is PageTextStatus.SPARSE_EMBEDDED_TEXT


def test_repeated_extraction_is_byte_identical_and_idempotent(
    tmp_path: Path, text_pdf_factory: TextPdfFactory
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(
        text_pdf_factory(tmp_path / "document.pdf", ["Deterministic text"]), store=store
    )

    first = extract_document_text(manifest.document_id, store=store)
    path = _artifact_path(store, first.document_id, first.artifact_id)
    first_bytes = path.read_bytes()
    second = extract_document_text(manifest.document_id, store=store)

    assert second == first
    assert path.read_bytes() == first_bytes == serialize_text_extraction(first)
    assert list(path.parent.glob("*.json")) == [path]


def test_extractor_version_participates_in_identity(
    tmp_path: Path,
    text_pdf_factory: TextPdfFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(
        text_pdf_factory(tmp_path / "document.pdf", ["Versioned text"]), store=store
    )
    first = extract_document_text(manifest.document_id, store=store)
    changed = replace(first.extractor, version="2")
    monkeypatch.setattr(
        "pagetrace.extraction.extraction.current_extractor_descriptor", lambda: changed
    )

    second = extract_document_text(manifest.document_id, store=store)

    assert second.extractor.version == "2"
    assert second.artifact_id != first.artifact_id


def test_provenance_links_artifact_page_manifest_document_and_fingerprint(
    tmp_path: Path, text_pdf_factory: TextPdfFactory
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(
        text_pdf_factory(tmp_path / "trace.pdf", ["Traceable text"]), store=store
    )

    artifact = extract_document_text(manifest.document_id, store=store)
    loaded_manifest = load_document(artifact.document_id, store=store)

    assert artifact.document_fingerprint == loaded_manifest.fingerprint
    assert artifact.pages[0].page_id == loaded_manifest.pages[0].page_id
    assert artifact.pages[0].page_number == loaded_manifest.pages[0].page_number
    assert artifact.extractor.pdf_backend_name == "pypdf"
    assert artifact.extractor.pdf_backend_version == version("pypdf")
    assert artifact.schema_version == EXTRACTION_SCHEMA_VERSION == 1


def test_persisted_readback_is_equal_and_immutable(
    tmp_path: Path, text_pdf_factory: TextPdfFactory
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(
        text_pdf_factory(tmp_path / "document.pdf", ["Immutable text"]), store=store
    )
    artifact = extract_document_text(manifest.document_id, store=store)

    loaded = load_text_extraction(
        artifact.artifact_id, document_id=manifest.document_id, store=store
    )

    assert loaded == artifact
    with pytest.raises(AttributeError):
        _assign_attribute(loaded, "page_count", 7)
    with pytest.raises(AttributeError):
        _assign_attribute(loaded.pages[0], "text", "changed")


def test_canonical_artifact_excludes_environmental_identity(
    tmp_path: Path, text_pdf_factory: TextPdfFactory
) -> None:
    store = tmp_path / "store"
    source = text_pdf_factory(tmp_path / "private-source-name.pdf", ["Canonical text"])
    manifest = ingest_document(source, store=store)

    payload = json.loads(
        serialize_text_extraction(extract_document_text(manifest.document_id, store=store))
    )
    serialized = json.dumps(payload)

    assert "private-source-name" not in serialized
    assert str(tmp_path) not in serialized
    assert "timestamp" not in payload
    assert "hostname" not in payload
    assert "username" not in payload


def _artifact_path(store: Path, document_id: str, artifact_id: str) -> Path:
    return store / "documents" / document_id / "artifacts" / "text" / f"{artifact_id}.json"


def _assign_attribute(value: object, name: str, replacement: object) -> None:
    setattr(value, name, replacement)
