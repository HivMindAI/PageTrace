from __future__ import annotations

import copy
import os
from pathlib import Path

import pytest

import pagetrace.ocr.storage as storage
from pagetrace.documents import DocumentManifest
from pagetrace.extraction import PageTextStatus, TextExtractionArtifact
from pagetrace.ocr import OcrArtifact, OcrIntegrityError, OcrStorageError, load_ocr_artifact
from pagetrace.ocr.engine import OcrEngineResult
from pagetrace.ocr.processing import ocr_document
from tests.conftest import ImageFactory
from tests.test_ocr import _artifact_path, _install_fake_runtime, _stored_image


def test_missing_and_oversized_artifacts_are_rejected(
    tmp_path: Path,
    image_factory: ImageFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manifest, _text_artifact, artifact = _persisted(tmp_path, image_factory, monkeypatch)
    missing = f"ocr-sha256-{'0' * 64}"
    with pytest.raises(OcrStorageError, match="does not exist"):
        load_ocr_artifact(missing, document_id=manifest.document_id, store=store)

    monkeypatch.setattr(storage, "_MAX_OCR_ARTIFACT_BYTES", 1)
    with pytest.raises(OcrIntegrityError, match="readback size"):
        load_ocr_artifact(
            artifact.artifact_id,
            document_id=manifest.document_id,
            store=store,
        )


def test_atomic_persistence_failure_cleans_temporary_file(
    tmp_path: Path,
    image_factory: ImageFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manifest, text_artifact = _stored_image(tmp_path, image_factory)
    _install_fake_runtime(
        monkeypatch,
        manifest.media_type,
        (OcrEngineResult(("text",), (0.9,)),),
    )

    def fail_link(_source: os.PathLike[str], _destination: os.PathLike[str]) -> None:
        raise OSError("promotion failed")

    monkeypatch.setattr("pagetrace.ocr.storage.os.link", fail_link)
    with pytest.raises(OcrStorageError, match="atomically persist"):
        ocr_document(manifest.document_id, text_artifact.artifact_id, store=store)

    ocr_directory = store / "documents" / manifest.document_id / "artifacts" / "ocr"
    assert list(ocr_directory.glob("*.tmp")) == []


def test_ocr_storage_component_must_be_a_directory(
    tmp_path: Path,
    image_factory: ImageFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manifest, text_artifact = _stored_image(tmp_path, image_factory)
    ocr_path = store / "documents" / manifest.document_id / "artifacts" / "ocr"
    ocr_path.write_text("not a directory", encoding="utf-8")
    _install_fake_runtime(
        monkeypatch,
        manifest.media_type,
        (OcrEngineResult(("text",), (0.9,)),),
    )

    with pytest.raises(OcrStorageError, match="storage"):
        ocr_document(manifest.document_id, text_artifact.artifact_id, store=store)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("document_id", "document_id"),
        ("document_fingerprint", "fingerprint"),
        ("source_fingerprint", "source text fingerprint"),
        ("page_count", "page count"),
        ("page_id", "page identities"),
        ("source_status", "routing statuses"),
        ("renderer", "renderer provenance"),
    ],
)
def test_provenance_validation_rejects_every_cross_artifact_mismatch(
    tmp_path: Path,
    image_factory: ImageFactory,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    message: str,
) -> None:
    _store, manifest, text_artifact, artifact = _persisted(tmp_path, image_factory, monkeypatch)
    changed = copy.copy(artifact)
    if mutation == "document_id":
        object.__setattr__(changed, "document_id", f"sha256-{'9' * 64}")
    elif mutation == "document_fingerprint":
        object.__setattr__(changed, "document_fingerprint", "9" * 64)
    elif mutation == "source_fingerprint":
        object.__setattr__(changed, "source_text_content_fingerprint", "9" * 64)
    elif mutation == "page_count":
        object.__setattr__(changed, "page_count", 2)
    elif mutation == "page_id":
        page = copy.copy(changed.pages[0])
        object.__setattr__(page, "page_id", "wrong")
        object.__setattr__(changed, "pages", (page,))
    elif mutation == "source_status":
        page = copy.copy(changed.pages[0])
        object.__setattr__(page, "source_status", PageTextStatus.EMBEDDED_TEXT)
        object.__setattr__(changed, "pages", (page,))
    else:
        processor = copy.copy(changed.processor)
        object.__setattr__(processor, "pdf_renderer_name", "pypdfium2")
        object.__setattr__(processor, "pdf_renderer_version", "5.13.0")
        object.__setattr__(changed, "processor", processor)

    with pytest.raises(OcrIntegrityError, match=message):
        storage._validate_provenance(changed, manifest, text_artifact)


def test_existing_contradictory_artifact_is_never_overwritten(
    tmp_path: Path,
    image_factory: ImageFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _manifest, _text_artifact, artifact = _persisted(tmp_path, image_factory, monkeypatch)
    monkeypatch.setattr(storage, "load_ocr_artifact", lambda *_args, **_kwargs: object())

    with pytest.raises(OcrIntegrityError, match="contradicts"):
        storage._load_expected(artifact, store=store)


def _persisted(
    tmp_path: Path,
    image_factory: ImageFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, DocumentManifest, TextExtractionArtifact, OcrArtifact]:
    store, manifest, text_artifact = _stored_image(tmp_path, image_factory)
    _install_fake_runtime(
        monkeypatch,
        manifest.media_type,
        (OcrEngineResult(("text",), (0.9,)),),
    )
    artifact = ocr_document(manifest.document_id, text_artifact.artifact_id, store=store)
    assert _artifact_path(store, manifest.document_id, artifact.artifact_id).is_file()
    return store, manifest, text_artifact, artifact
