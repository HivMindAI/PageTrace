"""Atomic persistence and integrity-checked readback for text artifacts."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from pagetrace.documents import DocumentManifest, MediaType, load_document
from pagetrace.documents.models import is_document_id
from pagetrace.extraction.errors import ExtractionIntegrityError, ExtractionStorageError
from pagetrace.extraction.models import (
    ExtractionMethod,
    TextExtractionArtifact,
    is_extraction_id,
)
from pagetrace.extraction.serialization import (
    deserialize_text_extraction,
    serialize_text_extraction,
)

_MAX_TEXT_ARTIFACT_BYTES = 128 * 1024 * 1024


def persist_text_extraction(
    artifact: TextExtractionArtifact, *, store: Path
) -> TextExtractionArtifact:
    """Promote one complete canonical artifact without overwriting contradictions."""

    manifest = load_document(artifact.document_id, store=Path(store))
    _validate_document_link(artifact, manifest)
    directory = _ensure_text_directory(artifact.document_id, store=Path(store))
    destination = directory / f"{artifact.artifact_id}.json"
    if destination.is_symlink() or destination.exists():
        return _load_expected(artifact, store=Path(store))

    data = serialize_text_extraction(artifact)
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
    except (ExtractionIntegrityError, ExtractionStorageError):
        raise
    except OSError as exc:
        raise ExtractionStorageError("could not atomically persist the text artifact") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_path is not None and temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError as exc:
                raise ExtractionStorageError("could not remove a temporary text artifact") from exc

    return _load_expected(artifact, store=Path(store))


def load_text_extraction(
    artifact_id: str,
    *,
    document_id: str,
    store: Path,
) -> TextExtractionArtifact:
    """Load a typed artifact and verify it against its still-trusted source document."""

    if not is_document_id(document_id):
        raise ExtractionIntegrityError("document_id is not a safe canonical identifier")
    if not is_extraction_id(artifact_id):
        raise ExtractionIntegrityError("artifact_id is not a safe canonical identifier")

    manifest = load_document(document_id, store=Path(store))
    root = Path(store).expanduser().resolve()
    artifact_directory = root / "documents" / document_id / "artifacts"
    text_directory = artifact_directory / "text"
    path = text_directory / f"{artifact_id}.json"
    for directory in (artifact_directory, text_directory):
        if directory.is_symlink():
            raise ExtractionIntegrityError("text artifact storage path is unsafe")
    if path.is_symlink():
        raise ExtractionIntegrityError("stored text artifact is unsafe")
    if not path.is_file():
        raise ExtractionStorageError(f"stored text artifact does not exist: {artifact_id}")

    try:
        if path.stat().st_size > _MAX_TEXT_ARTIFACT_BYTES:
            raise ExtractionIntegrityError("stored text artifact exceeds the readback size limit")
        artifact = deserialize_text_extraction(path.read_bytes())
    except ExtractionIntegrityError:
        raise
    except OSError as exc:
        raise ExtractionStorageError("could not read the stored text artifact") from exc

    if artifact.artifact_id != artifact_id:
        raise ExtractionIntegrityError("stored text artifact identity does not match its filename")
    _validate_document_link(artifact, manifest)
    return artifact


def _ensure_text_directory(document_id: str, *, store: Path) -> Path:
    root = Path(store).expanduser().resolve()
    document_directory = root / "documents" / document_id
    artifact_directory = document_directory / "artifacts"
    text_directory = artifact_directory / "text"
    for directory in (artifact_directory, text_directory):
        try:
            if directory.is_symlink():
                raise ExtractionIntegrityError("text artifact storage path is unsafe")
            directory.mkdir(exist_ok=True)
            if directory.is_symlink() or not directory.is_dir():
                raise ExtractionStorageError("text artifact storage path must be a directory")
        except ExtractionIntegrityError:
            raise
        except OSError as exc:
            raise ExtractionStorageError("could not initialize text artifact storage") from exc
    return text_directory


def _validate_document_link(artifact: TextExtractionArtifact, manifest: DocumentManifest) -> None:
    if artifact.document_id != manifest.document_id:
        raise ExtractionIntegrityError("text artifact document_id does not match the document")
    if artifact.document_fingerprint != manifest.fingerprint:
        raise ExtractionIntegrityError("text artifact fingerprint does not match the document")
    if artifact.page_count != manifest.page_count:
        raise ExtractionIntegrityError("text artifact page count does not match the document")
    if tuple(page.page_id for page in artifact.pages) != tuple(
        page.page_id for page in manifest.pages
    ):
        raise ExtractionIntegrityError("text artifact page identities do not match the document")

    expected_method = (
        ExtractionMethod.PYPDF_EMBEDDED_TEXT
        if manifest.media_type is MediaType.PDF
        else ExtractionMethod.OCR_ROUTING_ONLY
    )
    if any(page.method is not expected_method for page in artifact.pages):
        raise ExtractionIntegrityError("page extraction method does not match document media type")


def _load_expected(expected: TextExtractionArtifact, *, store: Path) -> TextExtractionArtifact:
    existing = load_text_extraction(
        expected.artifact_id,
        document_id=expected.document_id,
        store=Path(store),
    )
    if existing != expected:
        raise ExtractionIntegrityError(
            "existing text artifact contradicts deterministic extraction output"
        )
    return existing
