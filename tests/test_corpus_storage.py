from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import pagetrace.corpus.processing as corpus_processing
import pagetrace.corpus.storage as corpus_storage
from pagetrace.corpus import (
    CorpusIntegrityError,
    CorpusStorageError,
    build_corpus,
    build_corpus_artifact,
    corpus_content_fingerprint_for,
    load_corpus_artifact,
)
from pagetrace.corpus.models import text_fingerprint_for
from pagetrace.corpus.storage import persist_corpus_artifact
from tests.test_corpus_models import _source


def test_build_persist_and_load_reverify_complete_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source((("PageTrace", "corpus"),))
    store = _store_for(tmp_path, source.document_id)
    monkeypatch.setattr(
        corpus_storage, "load_structured_document", lambda *_args, **_kwargs: source
    )

    artifact = persist_corpus_artifact(build_corpus_artifact(source), store=store)

    assert (
        load_corpus_artifact(artifact.artifact_id, document_id=source.document_id, store=store)
        == artifact
    )
    assert persist_corpus_artifact(artifact, store=store) == artifact


def test_public_builder_loads_structure_and_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source((("text",),))
    expected = build_corpus_artifact(source)
    monkeypatch.setattr(
        corpus_processing, "load_structured_document", lambda *_args, **_kwargs: source
    )
    monkeypatch.setattr(
        corpus_processing, "persist_corpus_artifact", lambda artifact, **_kwargs: artifact
    )

    assert (
        build_corpus(source.document_id, source.artifact_id, store=tmp_path / "store") == expected
    )


def test_load_rejects_unsafe_missing_misnamed_and_oversized_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source((("text",),))
    store = _store_for(tmp_path, source.document_id)
    monkeypatch.setattr(
        corpus_storage, "load_structured_document", lambda *_args, **_kwargs: source
    )
    artifact = persist_corpus_artifact(build_corpus_artifact(source), store=store)
    directory = store / "documents" / source.document_id / "artifacts" / "corpus"
    original = directory / f"{artifact.artifact_id}.json"

    with pytest.raises(CorpusIntegrityError, match="safe corpus"):
        load_corpus_artifact("../bad", document_id=source.document_id, store=store)
    with pytest.raises(CorpusIntegrityError, match="document_id"):
        load_corpus_artifact(artifact.artifact_id, document_id="../bad", store=store)
    missing = f"corpus-sha256-{'f' * 64}"
    with pytest.raises(CorpusStorageError, match="does not exist"):
        load_corpus_artifact(missing, document_id=source.document_id, store=store)

    (directory / f"{missing}.json").write_bytes(original.read_bytes())
    with pytest.raises(CorpusIntegrityError, match="filename"):
        load_corpus_artifact(missing, document_id=source.document_id, store=store)

    monkeypatch.setattr(corpus_storage, "_MAX_CORPUS_ARTIFACT_BYTES", 1)
    with pytest.raises(CorpusIntegrityError, match="readback size limit"):
        load_corpus_artifact(artifact.artifact_id, document_id=source.document_id, store=store)
    original.unlink()
    with pytest.raises(CorpusIntegrityError, match="persistence size limit"):
        persist_corpus_artifact(artifact, store=store)


def test_tampering_and_source_contradictions_fail_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source((("PageTrace",),))
    store = _store_for(tmp_path, source.document_id)
    monkeypatch.setattr(
        corpus_storage, "load_structured_document", lambda *_args, **_kwargs: source
    )
    artifact = persist_corpus_artifact(build_corpus_artifact(source), store=store)
    path = (
        store
        / "documents"
        / source.document_id
        / "artifacts"
        / "corpus"
        / f"{artifact.artifact_id}.json"
    )
    path.write_bytes(path.read_bytes().replace(b"PageTrace", b"PageTracz"))
    with pytest.raises(CorpusIntegrityError, match="content_fingerprint"):
        load_corpus_artifact(artifact.artifact_id, document_id=source.document_id, store=store)

    changed_source = _source((("different",),))
    monkeypatch.setattr(
        corpus_storage, "load_structured_document", lambda *_args, **_kwargs: changed_source
    )
    with pytest.raises(CorpusIntegrityError, match="provenance fingerprint"):
        corpus_storage._validate_provenance(artifact, store=store)


def test_valid_but_changed_chunk_contradicts_source_reconstruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source((("text",),))
    artifact = build_corpus_artifact(source)
    chunk = artifact.chunks[0]
    changed_chunk = replace(
        chunk,
        text="next",
        content_fingerprint=text_fingerprint_for("next"),
    )
    changed_chunks = (changed_chunk,)
    contradiction = replace(
        artifact,
        chunks=changed_chunks,
        content_fingerprint=corpus_content_fingerprint_for(changed_chunks),
    )
    monkeypatch.setattr(
        corpus_storage, "load_structured_document", lambda *_args, **_kwargs: source
    )

    with pytest.raises(CorpusIntegrityError, match="contradicts deterministic"):
        corpus_storage._validate_provenance(contradiction, store=Path("unused"))


def _store_for(tmp_path: Path, document_id: str) -> Path:
    store = tmp_path / "store"
    (store / "documents" / document_id / "artifacts").mkdir(parents=True)
    return store
