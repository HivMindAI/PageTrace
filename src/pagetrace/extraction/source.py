"""Race-aware byte readback for verified stored document sources."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from pagetrace.documents import DocumentManifest, MediaType
from pagetrace.extraction.errors import ExtractionIntegrityError

_HASH_CHUNK_SIZE = 1024 * 1024
_SOURCE_NAMES = {
    MediaType.PDF: "source.pdf",
    MediaType.PNG: "source.png",
    MediaType.JPEG: "source.jpg",
}


def read_verified_source(manifest: DocumentManifest, *, store: Path) -> bytes:
    """Read source bytes through the same regular-file identity that was inspected."""

    source_path = (
        store.expanduser().resolve()
        / "documents"
        / manifest.document_id
        / _SOURCE_NAMES[manifest.media_type]
    )
    try:
        initial = source_path.lstat()
    except OSError as exc:
        raise ExtractionIntegrityError(
            "verified source could not be inspected for extraction"
        ) from exc
    if stat.S_ISLNK(initial.st_mode) or not stat.S_ISREG(initial.st_mode):
        raise ExtractionIntegrityError("verified source is no longer a safe regular file")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source_path, flags)
    except OSError as exc:
        raise ExtractionIntegrityError("verified source could not be opened safely") from exc

    digest = hashlib.sha256()
    source = bytearray()
    try:
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or (
                opened.st_dev != initial.st_dev or opened.st_ino != initial.st_ino
            ):
                raise ExtractionIntegrityError("verified source changed while it was being opened")
            while chunk := stream.read(_HASH_CHUNK_SIZE):
                digest.update(chunk)
                source.extend(chunk)
            after = os.fstat(stream.fileno())
    except ExtractionIntegrityError:
        raise
    except OSError as exc:
        raise ExtractionIntegrityError("verified source could not be read for extraction") from exc

    if opened.st_size != after.st_size or len(source) != manifest.byte_size:
        raise ExtractionIntegrityError("verified source size changed before extraction")
    if digest.hexdigest() != manifest.fingerprint:
        raise ExtractionIntegrityError("verified source fingerprint changed before extraction")
    return bytes(source)
