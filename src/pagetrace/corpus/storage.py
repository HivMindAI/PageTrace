"""Atomic persistence and full lineage validation for corpus artifacts."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from pagetrace.corpus.chunking import build_corpus_artifact
from pagetrace.corpus.errors import CorpusError, CorpusIntegrityError, CorpusStorageError
from pagetrace.corpus.models import CorpusArtifact, is_corpus_artifact_id
from pagetrace.corpus.serialization import deserialize_corpus_artifact, serialize_corpus_artifact
from pagetrace.documents.models import is_document_id
from pagetrace.structure import load_structured_document

_MAX_CORPUS_ARTIFACT_BYTES = 512 * 1024 * 1024


def persist_corpus_artifact(artifact: CorpusArtifact, *, store: Path) -> CorpusArtifact:
    """Atomically promote a complete corpus without overwriting contradictions."""

    _validate_provenance(artifact, store=Path(store))
    directory = _ensure_corpus_directory(artifact.document_id, store=Path(store))
    destination = directory / f"{artifact.artifact_id}.json"
    if destination.is_symlink() or destination.exists():
        return _load_expected(artifact, store=Path(store))
    data = serialize_corpus_artifact(artifact)
    if len(data) > _MAX_CORPUS_ARTIFACT_BYTES:
        raise CorpusIntegrityError("corpus artifact exceeds persistence size limit")
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
    except CorpusError:
        raise
    except OSError as exc:
        raise CorpusStorageError("could not atomically persist corpus artifact") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_path is not None and temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError as exc:
                raise CorpusStorageError("could not remove a temporary corpus artifact") from exc
    return _load_expected(artifact, store=Path(store))


def load_corpus_artifact(
    artifact_id: str,
    *,
    document_id: str,
    store: Path,
) -> CorpusArtifact:
    """Load a corpus and re-verify its complete deterministic source lineage."""

    if not is_document_id(document_id):
        raise CorpusIntegrityError("document_id is not a safe canonical identifier")
    if not is_corpus_artifact_id(artifact_id):
        raise CorpusIntegrityError("artifact_id is not a safe corpus identifier")
    root = Path(store).expanduser().resolve()
    artifact_directory = root / "documents" / document_id / "artifacts"
    corpus_directory = artifact_directory / "corpus"
    path = corpus_directory / f"{artifact_id}.json"
    for directory in (artifact_directory, corpus_directory):
        if directory.is_symlink():
            raise CorpusIntegrityError("corpus artifact storage path is unsafe")
    if path.is_symlink():
        raise CorpusIntegrityError("stored corpus artifact is unsafe")
    if not path.is_file():
        raise CorpusStorageError(f"stored corpus artifact does not exist: {artifact_id}")
    try:
        if path.stat().st_size > _MAX_CORPUS_ARTIFACT_BYTES:
            raise CorpusIntegrityError("stored corpus artifact exceeds readback size limit")
        data = path.read_bytes()
        if len(data) > _MAX_CORPUS_ARTIFACT_BYTES:
            raise CorpusIntegrityError("stored corpus artifact exceeds readback size limit")
        artifact = deserialize_corpus_artifact(data)
    except CorpusIntegrityError:
        raise
    except OSError as exc:
        raise CorpusStorageError("could not read stored corpus artifact") from exc
    if artifact.artifact_id != artifact_id:
        raise CorpusIntegrityError("stored corpus identity does not match its filename")
    if artifact.document_id != document_id:
        raise CorpusIntegrityError("stored corpus does not belong to the requested document")
    _validate_provenance(artifact, store=Path(store))
    return artifact


def _ensure_corpus_directory(document_id: str, *, store: Path) -> Path:
    root = Path(store).expanduser().resolve()
    artifact_directory = root / "documents" / document_id / "artifacts"
    corpus_directory = artifact_directory / "corpus"
    for directory in (artifact_directory, corpus_directory):
        try:
            if directory.is_symlink():
                raise CorpusIntegrityError("corpus artifact storage path is unsafe")
            directory.mkdir(exist_ok=True)
            if directory.is_symlink() or not directory.is_dir():
                raise CorpusStorageError("corpus artifact storage path must be a directory")
        except CorpusIntegrityError:
            raise
        except OSError as exc:
            raise CorpusStorageError("could not initialize corpus artifact storage") from exc
    return corpus_directory


def _validate_provenance(artifact: CorpusArtifact, *, store: Path) -> None:
    source = load_structured_document(
        artifact.source_structure_artifact_id,
        document_id=artifact.document_id,
        store=store,
    )
    if artifact.document_fingerprint != source.document_fingerprint:
        raise CorpusIntegrityError("corpus fingerprint does not match document")
    if artifact.source_structure_content_fingerprint != source.content_fingerprint:
        raise CorpusIntegrityError("corpus structure provenance fingerprint does not match")
    try:
        expected = build_corpus_artifact(
            source,
            configuration=artifact.configuration,
            processor=artifact.processor,
        )
    except (TypeError, ValueError, CorpusError) as exc:
        raise CorpusIntegrityError("corpus cannot be reconstructed from its source") from exc
    if artifact != expected:
        raise CorpusIntegrityError("corpus contradicts deterministic source reconstruction")


def _load_expected(expected: CorpusArtifact, *, store: Path) -> CorpusArtifact:
    existing = load_corpus_artifact(
        expected.artifact_id,
        document_id=expected.document_id,
        store=store,
    )
    if existing != expected:
        raise CorpusIntegrityError("existing corpus artifact contradicts deterministic output")
    return existing
