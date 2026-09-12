from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pypdf import PageObject
from pypdf.errors import PdfReadError

from pagetrace.documents import DocumentIntegrityError, ingest_document
from pagetrace.extraction import (
    ExtractionIntegrityError,
    ExtractionLimitError,
    ExtractionLimits,
    ExtractionProcessingError,
    ExtractionStorageError,
    TextExtractionConfig,
    extract_document_text,
    load_text_extraction,
)
from tests.conftest import ImageFactory, TextPdfFactory


def test_corrupted_artifact_json_is_rejected(
    tmp_path: Path, text_pdf_factory: TextPdfFactory
) -> None:
    store, document_id, artifact_id, path = _stored_text_artifact(tmp_path, text_pdf_factory)
    path.write_bytes(b"not JSON")

    with pytest.raises(ExtractionIntegrityError, match="UTF-8 JSON"):
        load_text_extraction(artifact_id, document_id=document_id, store=store)


def test_unknown_schema_version_is_rejected(
    tmp_path: Path, text_pdf_factory: TextPdfFactory
) -> None:
    store, document_id, artifact_id, path = _stored_text_artifact(tmp_path, text_pdf_factory)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = 2
    _write_payload(path, payload)

    with pytest.raises(ExtractionIntegrityError, match="schema version"):
        load_text_extraction(artifact_id, document_id=document_id, store=store)


def test_page_count_tampering_is_rejected(tmp_path: Path, text_pdf_factory: TextPdfFactory) -> None:
    store, document_id, artifact_id, path = _stored_text_artifact(tmp_path, text_pdf_factory)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["page_count"] = 2
    _write_payload(path, payload)

    with pytest.raises(ExtractionIntegrityError, match="page_count"):
        load_text_extraction(artifact_id, document_id=document_id, store=store)


def test_page_id_tampering_is_rejected(tmp_path: Path, text_pdf_factory: TextPdfFactory) -> None:
    store, document_id, artifact_id, path = _stored_text_artifact(tmp_path, text_pdf_factory)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["pages"][0]["page_id"] = f"{document_id}-page-000002"
    _write_payload(path, payload)

    with pytest.raises(ExtractionIntegrityError, match=r"content_fingerprint|page_id"):
        load_text_extraction(artifact_id, document_id=document_id, store=store)


def test_status_text_inconsistency_is_rejected(
    tmp_path: Path, text_pdf_factory: TextPdfFactory
) -> None:
    store, document_id, artifact_id, path = _stored_text_artifact(tmp_path, text_pdf_factory)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["pages"][0]["status"] = "ocr_candidate"
    _write_payload(path, payload)

    with pytest.raises(ExtractionIntegrityError, match="OCR-candidate"):
        load_text_extraction(artifact_id, document_id=document_id, store=store)


def test_text_content_tampering_is_rejected_by_content_fingerprint(
    tmp_path: Path, text_pdf_factory: TextPdfFactory
) -> None:
    store, document_id, artifact_id, path = _stored_text_artifact(tmp_path, text_pdf_factory)
    payload = json.loads(path.read_text(encoding="utf-8"))
    text = "Altered persisted text"
    payload["pages"][0]["text"] = text
    payload["pages"][0]["character_count"] = len(text)
    payload["pages"][0]["non_whitespace_character_count"] = sum(not char.isspace() for char in text)
    _write_payload(path, payload)

    with pytest.raises(ExtractionIntegrityError, match="content_fingerprint"):
        load_text_extraction(artifact_id, document_id=document_id, store=store)


def test_artifact_document_fingerprint_tampering_is_rejected(
    tmp_path: Path, text_pdf_factory: TextPdfFactory
) -> None:
    store, document_id, artifact_id, path = _stored_text_artifact(tmp_path, text_pdf_factory)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["document_fingerprint"] = "0" * 64
    _write_payload(path, payload)

    with pytest.raises(ExtractionIntegrityError, match=r"document_id|artifact_id"):
        load_text_extraction(artifact_id, document_id=document_id, store=store)


@pytest.mark.parametrize("artifact_id", ["../escape", "..\\escape", "sha256-not-text", ""])
def test_unsafe_artifact_id_cannot_escape_store(tmp_path: Path, artifact_id: str) -> None:
    document_id = f"sha256-{'0' * 64}"

    with pytest.raises(ExtractionIntegrityError, match="artifact_id"):
        load_text_extraction(artifact_id, document_id=document_id, store=tmp_path / "store")


@pytest.mark.parametrize("document_id", ["../escape", "..\\escape", "not-a-document", ""])
def test_unsafe_document_id_cannot_reach_artifact_paths(tmp_path: Path, document_id: str) -> None:
    artifact_id = f"text-sha256-{'0' * 64}"

    with pytest.raises(ExtractionIntegrityError, match="document_id"):
        load_text_extraction(artifact_id, document_id=document_id, store=tmp_path / "store")


def test_missing_text_artifact_has_a_clear_error(
    tmp_path: Path, image_factory: ImageFactory
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(
        image_factory(tmp_path / "image.png", image_format="PNG"), store=store
    )

    with pytest.raises(ExtractionStorageError, match="does not exist"):
        load_text_extraction(
            f"text-sha256-{'0' * 64}", document_id=manifest.document_id, store=store
        )


def test_source_tampering_invalidates_text_artifact_readback(
    tmp_path: Path, text_pdf_factory: TextPdfFactory
) -> None:
    store, document_id, artifact_id, _ = _stored_text_artifact(tmp_path, text_pdf_factory)
    source = store / "documents" / document_id / "source.pdf"
    source.write_bytes(source.read_bytes() + b"tampered")

    with pytest.raises(DocumentIntegrityError, match="byte size"):
        load_text_extraction(artifact_id, document_id=document_id, store=store)


def test_source_tampering_prevents_new_extraction(
    tmp_path: Path, text_pdf_factory: TextPdfFactory
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(
        text_pdf_factory(tmp_path / "document.pdf", ["Trusted text"]), store=store
    )
    source = store / "documents" / manifest.document_id / "source.pdf"
    source.write_bytes(source.read_bytes() + b"tampered")

    with pytest.raises(DocumentIntegrityError):
        extract_document_text(manifest.document_id, store=store)


def test_expected_pdf_parser_failure_is_a_page_specific_processing_error(
    tmp_path: Path,
    text_pdf_factory: TextPdfFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(
        text_pdf_factory(tmp_path / "document.pdf", ["Extract me"]), store=store
    )

    def fail_extraction(*_args: object, **_kwargs: object) -> str:
        raise PdfReadError("test parser failure")

    monkeypatch.setattr(PageObject, "extract_text", fail_extraction)
    with pytest.raises(ExtractionProcessingError, match="page 1"):
        extract_document_text(manifest.document_id, store=store)
    assert not (store / "documents" / manifest.document_id / "artifacts").exists()


def test_unexpected_programming_failure_is_not_hidden_as_an_ocr_candidate(
    tmp_path: Path,
    text_pdf_factory: TextPdfFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(
        text_pdf_factory(tmp_path / "document.pdf", ["Extract me"]), store=store
    )

    def fail_unexpectedly(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("unexpected test failure")

    monkeypatch.setattr(PageObject, "extract_text", fail_unexpectedly)
    with pytest.raises(RuntimeError, match="unexpected"):
        extract_document_text(manifest.document_id, store=store)


def test_invalid_backend_result_is_a_processing_error(
    tmp_path: Path,
    text_pdf_factory: TextPdfFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(
        text_pdf_factory(tmp_path / "document.pdf", ["Extract me"]), store=store
    )
    monkeypatch.setattr(PageObject, "extract_text", lambda *_args, **_kwargs: None)

    with pytest.raises(ExtractionProcessingError, match="invalid text value"):
        extract_document_text(manifest.document_id, store=store)


def test_failed_artifact_promotion_cleans_temporary_file(
    tmp_path: Path,
    text_pdf_factory: TextPdfFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(
        text_pdf_factory(tmp_path / "document.pdf", ["Persist me"]), store=store
    )

    def fail_link(_source: object, _destination: object) -> None:
        raise PermissionError("test denial")

    monkeypatch.setattr("pagetrace.extraction.storage.os.link", fail_link)
    with pytest.raises(ExtractionStorageError, match="atomically persist"):
        extract_document_text(manifest.document_id, store=store)

    text_directory = store / "documents" / manifest.document_id / "artifacts" / "text"
    assert list(text_directory.iterdir()) == []


def test_artifact_storage_component_must_be_a_directory(
    tmp_path: Path, text_pdf_factory: TextPdfFactory
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(
        text_pdf_factory(tmp_path / "document.pdf", ["Persist me"]), store=store
    )
    artifact_path = store / "documents" / manifest.document_id / "artifacts"
    artifact_path.write_text("not a directory", encoding="utf-8")

    with pytest.raises(ExtractionStorageError, match=r"directory|initialize"):
        extract_document_text(manifest.document_id, store=store)


def test_oversized_artifact_readback_is_rejected(
    tmp_path: Path,
    text_pdf_factory: TextPdfFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, document_id, artifact_id, _ = _stored_text_artifact(tmp_path, text_pdf_factory)
    monkeypatch.setattr("pagetrace.extraction.storage._MAX_TEXT_ARTIFACT_BYTES", 1)

    with pytest.raises(ExtractionIntegrityError, match="size limit"):
        load_text_extraction(artifact_id, document_id=document_id, store=store)


def test_repeated_extraction_rejects_a_self_consistent_contradictory_artifact(
    tmp_path: Path, text_pdf_factory: TextPdfFactory
) -> None:
    store, document_id, _artifact_id, path = _stored_text_artifact(tmp_path, text_pdf_factory)
    payload = json.loads(path.read_text(encoding="utf-8"))
    changed_text = "Different but internally checksummed text"
    page = payload["pages"][0]
    page["text"] = changed_text
    page["character_count"] = len(changed_text)
    page["non_whitespace_character_count"] = sum(not char.isspace() for char in changed_text)
    canonical_pages = json.dumps(
        payload["pages"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    payload["content_fingerprint"] = hashlib.sha256(canonical_pages).hexdigest()
    _write_payload(path, payload)

    with pytest.raises(ExtractionIntegrityError, match="contradicts"):
        extract_document_text(document_id, store=store)


def test_configuration_rejects_non_positive_or_boolean_thresholds() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        TextExtractionConfig(minimum_embedded_characters=0)
    with pytest.raises(ValueError, match="positive integer"):
        TextExtractionConfig(minimum_embedded_characters=True)


def test_page_character_limit_rejects_without_truncation_or_partial_artifact(
    tmp_path: Path,
    text_pdf_factory: TextPdfFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(
        text_pdf_factory(tmp_path / "document.pdf", ["ordinary text"]), store=store
    )
    extracted = "123456"
    monkeypatch.setattr(PageObject, "extract_text", lambda *_args, **_kwargs: extracted)
    configuration = TextExtractionConfig(
        limits=ExtractionLimits(max_characters_per_page=5, max_characters_per_document=10)
    )

    with pytest.raises(ExtractionLimitError, match="5-character per-page limit"):
        extract_document_text(manifest.document_id, store=store, configuration=configuration)

    assert len(extracted) == 6
    assert not (store / "documents" / manifest.document_id / "artifacts").exists()


def test_document_character_limit_is_enforced_incrementally(
    tmp_path: Path,
    text_pdf_factory: TextPdfFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(
        text_pdf_factory(tmp_path / "document.pdf", ["page one", "page two"]), store=store
    )
    monkeypatch.setattr(PageObject, "extract_text", lambda *_args, **_kwargs: "1234")
    configuration = TextExtractionConfig(
        limits=ExtractionLimits(max_characters_per_page=4, max_characters_per_document=7)
    )

    with pytest.raises(ExtractionLimitError, match="7-character total limit at page 2"):
        extract_document_text(manifest.document_id, store=store, configuration=configuration)

    assert not (store / "documents" / manifest.document_id / "artifacts").exists()


def test_character_limits_are_inclusive_at_the_exact_boundary(
    tmp_path: Path,
    text_pdf_factory: TextPdfFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(
        text_pdf_factory(tmp_path / "document.pdf", ["ordinary text"]), store=store
    )
    extracted = "12345"
    monkeypatch.setattr(PageObject, "extract_text", lambda *_args, **_kwargs: extracted)
    limits = ExtractionLimits(max_characters_per_page=5, max_characters_per_document=5)

    artifact = extract_document_text(
        manifest.document_id,
        store=store,
        configuration=TextExtractionConfig(limits=limits),
    )

    assert artifact.pages[0].text == extracted
    assert artifact.pages[0].character_count == 5
    assert artifact.configuration.limits == limits


def test_limit_policy_changes_artifact_identity_and_round_trips(
    tmp_path: Path,
    text_pdf_factory: TextPdfFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(
        text_pdf_factory(tmp_path / "document.pdf", ["ordinary text"]), store=store
    )
    monkeypatch.setattr(PageObject, "extract_text", lambda *_args, **_kwargs: "bounded text")
    first_limits = ExtractionLimits(max_characters_per_page=100, max_characters_per_document=1_000)
    second_limits = ExtractionLimits(max_characters_per_page=101, max_characters_per_document=1_000)

    first = extract_document_text(
        manifest.document_id,
        store=store,
        configuration=TextExtractionConfig(limits=first_limits),
    )
    second = extract_document_text(
        manifest.document_id,
        store=store,
        configuration=TextExtractionConfig(limits=second_limits),
    )
    loaded = load_text_extraction(first.artifact_id, document_id=manifest.document_id, store=store)

    assert first.artifact_id != second.artifact_id
    assert loaded.configuration.limits == first_limits


def test_limit_failure_does_not_damage_an_existing_valid_artifact(
    tmp_path: Path,
    text_pdf_factory: TextPdfFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(
        text_pdf_factory(tmp_path / "document.pdf", ["ordinary text"]), store=store
    )
    monkeypatch.setattr(PageObject, "extract_text", lambda *_args, **_kwargs: "stable text")
    valid = extract_document_text(manifest.document_id, store=store)
    valid_path = (
        store
        / "documents"
        / manifest.document_id
        / "artifacts"
        / "text"
        / f"{valid.artifact_id}.json"
    )
    original_bytes = valid_path.read_bytes()
    restrictive = TextExtractionConfig(
        limits=ExtractionLimits(max_characters_per_page=5, max_characters_per_document=5)
    )

    with pytest.raises(ExtractionLimitError):
        extract_document_text(manifest.document_id, store=store, configuration=restrictive)

    assert valid_path.read_bytes() == original_bytes
    assert (
        load_text_extraction(valid.artifact_id, document_id=manifest.document_id, store=store)
        == valid
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_characters_per_page", 0),
        ("max_characters_per_document", -1),
        ("max_characters_per_page", True),
        ("max_characters_per_document", "100"),
    ],
)
def test_persisted_invalid_extraction_limits_are_rejected(
    tmp_path: Path,
    text_pdf_factory: TextPdfFactory,
    field: str,
    value: object,
) -> None:
    store, document_id, artifact_id, path = _stored_text_artifact(tmp_path, text_pdf_factory)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["configuration"]["limits"][field] = value
    _write_payload(path, payload)

    with pytest.raises(ExtractionIntegrityError, match=r"configuration.limits|max_characters"):
        load_text_extraction(artifact_id, document_id=document_id, store=store)


def test_persisted_limits_require_every_schema_field(
    tmp_path: Path, text_pdf_factory: TextPdfFactory
) -> None:
    store, document_id, artifact_id, path = _stored_text_artifact(tmp_path, text_pdf_factory)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["configuration"]["limits"].pop("max_characters_per_document")
    _write_payload(path, payload)

    with pytest.raises(ExtractionIntegrityError, match="fields are invalid"):
        load_text_extraction(artifact_id, document_id=document_id, store=store)


def _stored_text_artifact(
    tmp_path: Path, text_pdf_factory: TextPdfFactory
) -> tuple[Path, str, str, Path]:
    store = tmp_path / "store"
    manifest = ingest_document(
        text_pdf_factory(tmp_path / "document.pdf", ["Stored digital text"]), store=store
    )
    artifact = extract_document_text(manifest.document_id, store=store)
    path = (
        store
        / "documents"
        / manifest.document_id
        / "artifacts"
        / "text"
        / f"{artifact.artifact_id}.json"
    )
    return store, manifest.document_id, artifact.artifact_id, path


def _write_payload(path: Path, payload: object) -> None:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    path.write_text(f"{text}\n", encoding="utf-8")
