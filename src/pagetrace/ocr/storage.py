"""Atomic persistence and provenance-checked readback for OCR artifacts."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from pagetrace.documents import DocumentManifest, MediaType, load_document
from pagetrace.documents.models import is_document_id
from pagetrace.extraction import TextExtractionArtifact, load_text_extraction
from pagetrace.ocr.errors import OcrIntegrityError, OcrStorageError
from pagetrace.ocr.models import OcrArtifact, is_ocr_artifact_id
from pagetrace.ocr.serialization import deserialize_ocr_artifact, serialize_ocr_artifact

_MAX_OCR_ARTIFACT_BYTES = 128 * 1024 * 1024


def persist_ocr_artifact(artifact: OcrArtifact, *, store: Path) -> OcrArtifact:
    """Promote one complete canonical OCR artifact without overwriting contradictions."""

    manifest, source_artifact = _load_provenance(artifact, store=Path(store))
    _validate_provenance(artifact, manifest, source_artifact)
    directory = _ensure_ocr_directory(artifact.document_id, store=Path(store))
    destination = directory / f"{artifact.artifact_id}.json"
    if destination.is_symlink() or destination.exists():
        return _load_expected(artifact, store=Path(store))

    data = serialize_ocr_artifact(artifact)
    descriptor = -1
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{artifact.artifact_id}-", suffix=".tmp", dir=directory
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary_path, destination)
        except FileExistsError:
            return _load_expected(artifact, store=Path(store))
    except (OcrIntegrityError, OcrStorageError):
        raise
    except OSError as exc:
        raise OcrStorageError("could not atomically persist the OCR artifact") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_path is not None and temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError as exc:
                raise OcrStorageError("could not remove a temporary OCR artifact") from exc
    return _load_expected(artifact, store=Path(store))


def load_ocr_artifact(
    artifact_id: str,
    *,
    document_id: str,
    store: Path,
) -> OcrArtifact:
    """Load an OCR artifact and verify its document and text-routing provenance."""

    if not is_document_id(document_id):
        raise OcrIntegrityError("document_id is not a safe canonical identifier")
    if not is_ocr_artifact_id(artifact_id):
        raise OcrIntegrityError("artifact_id is not a safe canonical OCR identifier")
    root = Path(store).expanduser().resolve()
    artifact_directory = root / "documents" / document_id / "artifacts"
    ocr_directory = artifact_directory / "ocr"
    path = ocr_directory / f"{artifact_id}.json"
    for directory in (artifact_directory, ocr_directory):
        if directory.is_symlink():
            raise OcrIntegrityError("OCR artifact storage path is unsafe")
    if path.is_symlink():
        raise OcrIntegrityError("stored OCR artifact is unsafe")
    if not path.is_file():
        raise OcrStorageError(f"stored OCR artifact does not exist: {artifact_id}")
    try:
        if path.stat().st_size > _MAX_OCR_ARTIFACT_BYTES:
            raise OcrIntegrityError("stored OCR artifact exceeds the readback size limit")
        artifact = deserialize_ocr_artifact(path.read_bytes())
    except OcrIntegrityError:
        raise
    except OSError as exc:
        raise OcrStorageError("could not read the stored OCR artifact") from exc

    if artifact.artifact_id != artifact_id:
        raise OcrIntegrityError("stored OCR artifact identity does not match its filename")
    manifest, source_artifact = _load_provenance(artifact, store=Path(store))
    _validate_provenance(artifact, manifest, source_artifact)
    return artifact


def _ensure_ocr_directory(document_id: str, *, store: Path) -> Path:
    root = Path(store).expanduser().resolve()
    document_directory = root / "documents" / document_id
    artifact_directory = document_directory / "artifacts"
    ocr_directory = artifact_directory / "ocr"
    for directory in (artifact_directory, ocr_directory):
        try:
            if directory.is_symlink():
                raise OcrIntegrityError("OCR artifact storage path is unsafe")
            directory.mkdir(exist_ok=True)
            if directory.is_symlink() or not directory.is_dir():
                raise OcrStorageError("OCR artifact storage path must be a directory")
        except OcrIntegrityError:
            raise
        except OSError as exc:
            raise OcrStorageError("could not initialize OCR artifact storage") from exc
    return ocr_directory


def _load_provenance(
    artifact: OcrArtifact, *, store: Path
) -> tuple[DocumentManifest, TextExtractionArtifact]:
    manifest = load_document(artifact.document_id, store=Path(store))
    source_artifact = load_text_extraction(
        artifact.source_text_artifact_id,
        document_id=artifact.document_id,
        store=Path(store),
    )
    return manifest, source_artifact


def _validate_provenance(
    artifact: OcrArtifact,
    manifest: DocumentManifest,
    source_artifact: TextExtractionArtifact,
) -> None:
    if artifact.document_id != manifest.document_id:
        raise OcrIntegrityError("OCR artifact document_id does not match the document")
    if artifact.document_fingerprint != manifest.fingerprint:
        raise OcrIntegrityError("OCR artifact fingerprint does not match the document")
    if artifact.source_text_content_fingerprint != source_artifact.content_fingerprint:
        raise OcrIntegrityError("OCR source text fingerprint does not match its artifact")
    if (
        artifact.page_count != manifest.page_count
        or artifact.page_count != source_artifact.page_count
    ):
        raise OcrIntegrityError("OCR artifact page count does not match its provenance")
    if tuple(page.page_id for page in artifact.pages) != tuple(
        page.page_id for page in source_artifact.pages
    ):
        raise OcrIntegrityError("OCR page identities do not match the text-routing artifact")
    if tuple(page.source_status for page in artifact.pages) != tuple(
        page.status for page in source_artifact.pages
    ):
        raise OcrIntegrityError("OCR page routing statuses do not match the source artifact")
    renderer_present = artifact.processor.pdf_renderer_name is not None
    if renderer_present != (manifest.media_type is MediaType.PDF):
        raise OcrIntegrityError("OCR renderer provenance does not match document media type")


def _load_expected(expected: OcrArtifact, *, store: Path) -> OcrArtifact:
    existing = load_ocr_artifact(
        expected.artifact_id,
        document_id=expected.document_id,
        store=Path(store),
    )
    if existing != expected:
        raise OcrIntegrityError("existing OCR artifact contradicts deterministic OCR output")
    return existing
