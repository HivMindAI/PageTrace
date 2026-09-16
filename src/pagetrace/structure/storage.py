"""Atomic persistence and cross-artifact validation for structured documents."""

from __future__ import annotations

import math
import os
import tempfile
from pathlib import Path

from pagetrace.documents import DimensionUnit, MediaType, load_document
from pagetrace.documents.models import is_document_id
from pagetrace.extraction import load_text_extraction
from pagetrace.ocr import load_ocr_artifact
from pagetrace.structure.errors import StructureIntegrityError, StructureStorageError
from pagetrace.structure.models import StructuredDocumentArtifact, is_structure_artifact_id
from pagetrace.structure.serialization import (
    deserialize_structured_document,
    serialize_structured_document,
)

_MAX_STRUCTURE_ARTIFACT_BYTES = 512 * 1024 * 1024


def persist_structured_document(
    artifact: StructuredDocumentArtifact, *, store: Path
) -> StructuredDocumentArtifact:
    """Atomically promote a complete artifact without overwriting contradictions."""

    _validate_provenance(artifact, store=Path(store))
    directory = _ensure_structure_directory(artifact.document_id, store=Path(store))
    destination = directory / f"{artifact.artifact_id}.json"
    if destination.is_symlink() or destination.exists():
        return _load_expected(artifact, store=Path(store))

    data = serialize_structured_document(artifact)
    if len(data) > _MAX_STRUCTURE_ARTIFACT_BYTES:
        raise StructureIntegrityError("structured artifact exceeds persistence size limit")
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
    except (StructureIntegrityError, StructureStorageError):
        raise
    except OSError as exc:
        raise StructureStorageError("could not atomically persist structured artifact") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_path is not None and temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError as exc:
                raise StructureStorageError(
                    "could not remove a temporary structured artifact"
                ) from exc
    return _load_expected(artifact, store=Path(store))


def load_structured_document(
    artifact_id: str,
    *,
    document_id: str,
    store: Path,
) -> StructuredDocumentArtifact:
    """Load structured output and re-verify all prior-stage provenance."""

    if not is_document_id(document_id):
        raise StructureIntegrityError("document_id is not a safe canonical identifier")
    if not is_structure_artifact_id(artifact_id):
        raise StructureIntegrityError("artifact_id is not a safe structure identifier")
    root = Path(store).expanduser().resolve()
    artifact_directory = root / "documents" / document_id / "artifacts"
    structure_directory = artifact_directory / "structure"
    path = structure_directory / f"{artifact_id}.json"
    for directory in (artifact_directory, structure_directory):
        if directory.is_symlink():
            raise StructureIntegrityError("structured artifact storage path is unsafe")
    if path.is_symlink():
        raise StructureIntegrityError("stored structured artifact is unsafe")
    if not path.is_file():
        raise StructureStorageError(f"stored structured artifact does not exist: {artifact_id}")
    try:
        if path.stat().st_size > _MAX_STRUCTURE_ARTIFACT_BYTES:
            raise StructureIntegrityError("stored structured artifact exceeds readback size limit")
        data = path.read_bytes()
        if len(data) > _MAX_STRUCTURE_ARTIFACT_BYTES:
            raise StructureIntegrityError("stored structured artifact exceeds readback size limit")
        artifact = deserialize_structured_document(data)
    except StructureIntegrityError:
        raise
    except OSError as exc:
        raise StructureStorageError("could not read stored structured artifact") from exc
    if artifact.artifact_id != artifact_id:
        raise StructureIntegrityError("stored structured identity does not match its filename")
    _validate_provenance(artifact, store=Path(store))
    return artifact


def _ensure_structure_directory(document_id: str, *, store: Path) -> Path:
    root = Path(store).expanduser().resolve()
    artifact_directory = root / "documents" / document_id / "artifacts"
    structure_directory = artifact_directory / "structure"
    for directory in (artifact_directory, structure_directory):
        try:
            if directory.is_symlink():
                raise StructureIntegrityError("structured artifact storage path is unsafe")
            directory.mkdir(exist_ok=True)
            if directory.is_symlink() or not directory.is_dir():
                raise StructureStorageError("structured artifact storage path must be a directory")
        except StructureIntegrityError:
            raise
        except OSError as exc:
            raise StructureStorageError("could not initialize structured artifact storage") from exc
    return structure_directory


def _validate_provenance(artifact: StructuredDocumentArtifact, *, store: Path) -> None:
    manifest = load_document(artifact.document_id, store=store)
    text_artifact = load_text_extraction(
        artifact.source_text_artifact_id,
        document_id=artifact.document_id,
        store=store,
    )
    ocr_artifact = load_ocr_artifact(
        artifact.source_ocr_artifact_id,
        document_id=artifact.document_id,
        store=store,
    )
    if artifact.document_fingerprint != manifest.fingerprint:
        raise StructureIntegrityError("structured fingerprint does not match document")
    if artifact.source_text_content_fingerprint != text_artifact.content_fingerprint:
        raise StructureIntegrityError("structured text provenance fingerprint does not match")
    if artifact.source_ocr_content_fingerprint != ocr_artifact.content_fingerprint:
        raise StructureIntegrityError("structured OCR provenance fingerprint does not match")
    if ocr_artifact.source_text_artifact_id != text_artifact.artifact_id:
        raise StructureIntegrityError("structured source artifacts do not share provenance")
    if artifact.page_count != manifest.page_count:
        raise StructureIntegrityError("structured page count does not match document")
    if tuple(page.page_id for page in artifact.pages) != tuple(
        page.page_id for page in manifest.pages
    ):
        raise StructureIntegrityError("structured page identities do not match document")
    tolerance = 10**-artifact.configuration.coordinate_precision
    for structured_page, manifest_page in zip(artifact.pages, manifest.pages, strict=True):
        expected_width = float(manifest_page.width)
        expected_height = float(manifest_page.height)
        if (
            manifest_page.dimension_unit is DimensionUnit.POINTS
            and manifest_page.rotation_degrees in (90, 270)
        ):
            expected_width, expected_height = expected_height, expected_width
        if structured_page.dimension_unit is not manifest_page.dimension_unit:
            raise StructureIntegrityError("structured page unit does not match document")
        if structured_page.source_rotation_degrees != manifest_page.rotation_degrees:
            raise StructureIntegrityError("structured page rotation does not match document")
        if not math.isclose(
            structured_page.width, expected_width, abs_tol=tolerance
        ) or not math.isclose(
            structured_page.height,
            expected_height,
            abs_tol=tolerance,
        ):
            raise StructureIntegrityError("structured page dimensions do not match document")
    backend_present = artifact.processor.pdf_layout_backend_name is not None
    if backend_present != (manifest.media_type is MediaType.PDF):
        raise StructureIntegrityError("structured layout backend does not match media type")


def _load_expected(
    expected: StructuredDocumentArtifact, *, store: Path
) -> StructuredDocumentArtifact:
    existing = load_structured_document(
        expected.artifact_id,
        document_id=expected.document_id,
        store=store,
    )
    if existing != expected:
        raise StructureIntegrityError(
            "existing structured artifact contradicts deterministic output"
        )
    return existing
