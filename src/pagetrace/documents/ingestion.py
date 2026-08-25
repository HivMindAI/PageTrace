"""Secure bounded staging orchestration for untrusted document paths."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
from pathlib import Path

from pagetrace.documents.detection import detect_media_type
from pagetrace.documents.errors import (
    DocumentLimitError,
    DocumentStorageError,
    InvalidDocumentError,
)
from pagetrace.documents.models import (
    DEFAULT_INGESTION_LIMITS,
    DocumentManifest,
    IngestionLimits,
    document_id_for,
)
from pagetrace.documents.storage import initialize_store, persist_document
from pagetrace.documents.validation import validate_staged_document

_COPY_CHUNK_SIZE = 1024 * 1024


def ingest_document(
    path: Path,
    *,
    store: Path,
    limits: IngestionLimits = DEFAULT_INGESTION_LIMITS,
) -> DocumentManifest:
    """Stage, validate, identify, and atomically persist one untrusted document."""

    source_path = Path(path)
    _, _, staging_root = initialize_store(Path(store))
    try:
        staging_directory = Path(tempfile.mkdtemp(prefix="ingest-", dir=staging_root))
    except OSError as exc:
        raise DocumentStorageError("could not create a secure staging directory") from exc

    staged_source = staging_directory / "input.bin"
    try:
        fingerprint, byte_size = _stage_input(source_path, staged_source, limits)
        document_id = document_id_for(fingerprint)
        media_type = detect_media_type(staged_source)
        manifest = validate_staged_document(
            staged_source,
            media_type,
            document_id=document_id,
            fingerprint=fingerprint,
            byte_size=byte_size,
            limits=limits,
        )
        return persist_document(
            staged_source,
            staging_directory,
            manifest,
            store=Path(store),
        )
    finally:
        if staging_directory.exists():
            try:
                shutil.rmtree(staging_directory)
            except OSError as exc:
                raise DocumentStorageError(
                    "could not remove the temporary staging artifact"
                ) from exc


def _stage_input(source_path: Path, staged_path: Path, limits: IngestionLimits) -> tuple[str, int]:
    try:
        initial = source_path.lstat()
    except FileNotFoundError as exc:
        raise InvalidDocumentError("input document does not exist") from exc
    except OSError as exc:
        raise InvalidDocumentError("input document path could not be inspected") from exc

    if stat.S_ISLNK(initial.st_mode):
        raise InvalidDocumentError("symbolic-link document inputs are not supported")
    if not stat.S_ISREG(initial.st_mode):
        raise InvalidDocumentError("input document must be a regular file")
    if initial.st_size == 0:
        raise InvalidDocumentError("input document is empty")
    if initial.st_size > limits.max_file_bytes:
        raise DocumentLimitError(f"input exceeds the {limits.max_file_bytes}-byte ingestion limit")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source_path, flags)
    except OSError as exc:
        raise InvalidDocumentError("input document could not be opened safely") from exc

    digest = hashlib.sha256()
    byte_size = 0
    try:
        with os.fdopen(descriptor, "rb") as source, staged_path.open("xb") as target:
            opened = os.fstat(source.fileno())
            if not stat.S_ISREG(opened.st_mode) or (
                opened.st_dev != initial.st_dev or opened.st_ino != initial.st_ino
            ):
                raise InvalidDocumentError("input document changed while it was being opened")
            while chunk := source.read(_COPY_CHUNK_SIZE):
                byte_size += len(chunk)
                if byte_size > limits.max_file_bytes:
                    raise DocumentLimitError(
                        f"input exceeds the {limits.max_file_bytes}-byte ingestion limit"
                    )
                digest.update(chunk)
                target.write(chunk)
            after = os.fstat(source.fileno())
            target.flush()
            os.fsync(target.fileno())
    except (DocumentLimitError, InvalidDocumentError):
        raise
    except OSError as exc:
        raise InvalidDocumentError("input document could not be staged") from exc

    if byte_size == 0:
        raise InvalidDocumentError("input document is empty")
    if (
        opened.st_size != initial.st_size
        or after.st_size != initial.st_size
        or after.st_mtime_ns != initial.st_mtime_ns
        or byte_size != initial.st_size
    ):
        raise InvalidDocumentError("input document changed during ingestion")
    return digest.hexdigest(), byte_size
