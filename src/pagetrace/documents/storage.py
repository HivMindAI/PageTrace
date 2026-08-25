"""Atomic content-addressed persistence and verified manifest readback."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from pagetrace.documents.errors import DocumentIntegrityError, DocumentStorageError
from pagetrace.documents.manifest import deserialize_manifest, serialize_manifest
from pagetrace.documents.models import DocumentManifest, MediaType, is_document_id

_HASH_CHUNK_SIZE = 1024 * 1024
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_SOURCE_NAMES = {
    MediaType.PDF: "source.pdf",
    MediaType.PNG: "source.png",
    MediaType.JPEG: "source.jpg",
}


def initialize_store(store: Path) -> tuple[Path, Path, Path]:
    """Create and return the normalized root, documents, and staging directories."""

    root = store.expanduser().resolve()
    documents = root / "documents"
    staging = root / ".staging"
    try:
        documents.mkdir(parents=True, exist_ok=True)
        staging.mkdir(parents=True, exist_ok=True)
        if not documents.is_dir() or not staging.is_dir():
            raise DocumentStorageError("store paths must be directories")
    except OSError as exc:
        raise DocumentStorageError("could not initialize the PageTrace document store") from exc
    return root, documents, staging


def persist_document(
    staged_source: Path,
    staging_directory: Path,
    manifest: DocumentManifest,
    *,
    store: Path,
) -> DocumentManifest:
    """Atomically promote a complete staged artifact into content-addressed storage."""

    _, documents, _ = initialize_store(store)
    destination = documents / manifest.document_id
    if destination.exists():
        return _load_expected(manifest, store=store)

    source_name = _SOURCE_NAMES[manifest.media_type]
    completed_source = staging_directory / source_name
    manifest_path = staging_directory / "manifest.json"
    try:
        staged_source.replace(completed_source)
        _write_fsynced(manifest_path, serialize_manifest(manifest))
        os.replace(staging_directory, destination)
    except OSError as exc:
        if destination.exists():
            return _load_expected(manifest, store=store)
        raise DocumentStorageError("could not atomically persist the document artifact") from exc

    return _load_expected(manifest, store=store)


def load_document(document_id: str, *, store: Path) -> DocumentManifest:
    """Load a stored manifest and verify its structure, identity, and source fingerprint."""

    if not is_document_id(document_id):
        raise DocumentIntegrityError("document_id is not a safe canonical identifier")

    root = store.expanduser().resolve()
    artifact = root / "documents" / document_id
    manifest_path = artifact / "manifest.json"
    if artifact.is_symlink() or not artifact.is_dir():
        raise DocumentStorageError(f"stored document does not exist: {document_id}")
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise DocumentIntegrityError("stored manifest is missing or unsafe")
    try:
        if manifest_path.stat().st_size > _MAX_MANIFEST_BYTES:
            raise DocumentIntegrityError("stored manifest exceeds the readback size limit")
        manifest = deserialize_manifest(manifest_path.read_bytes())
    except DocumentIntegrityError:
        raise
    except OSError as exc:
        raise DocumentStorageError("could not read the stored manifest") from exc

    if manifest.document_id != document_id:
        raise DocumentIntegrityError("stored manifest identity does not match its directory")
    source_path = artifact / _SOURCE_NAMES[manifest.media_type]
    if source_path.is_symlink() or not source_path.is_file():
        raise DocumentIntegrityError("stored source is missing or unsafe")

    digest, byte_size = _fingerprint_file(source_path)
    if byte_size != manifest.byte_size:
        raise DocumentIntegrityError("stored source byte size does not match the manifest")
    if digest != manifest.fingerprint:
        raise DocumentIntegrityError("stored source fingerprint does not match the manifest")
    return manifest


def _load_expected(expected: DocumentManifest, *, store: Path) -> DocumentManifest:
    existing = load_document(expected.document_id, store=store)
    if existing != expected:
        raise DocumentIntegrityError(
            "existing content-addressed artifact conflicts with the validated manifest"
        )
    return existing


def _write_fsynced(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _fingerprint_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_size = 0
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(_HASH_CHUNK_SIZE):
                digest.update(chunk)
                byte_size += len(chunk)
    except OSError as exc:
        raise DocumentStorageError("could not verify the stored source") from exc
    return digest.hexdigest(), byte_size
