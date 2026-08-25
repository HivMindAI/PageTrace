from __future__ import annotations

import json
import os
import runpy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import pagetrace.cli
from pagetrace.documents import (
    DocumentIntegrityError,
    DocumentLimitError,
    DocumentMetadata,
    DocumentStorageError,
    IngestionLimits,
    InvalidDocumentError,
    MediaType,
    ingest_document,
    load_document,
    serialize_manifest,
)
from pagetrace.documents.detection import detect_media_type
from pagetrace.documents.ingestion import _stage_input
from tests.conftest import ImageFactory, PdfFactory


def test_module_entry_point_returns_cli_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pagetrace.cli, "main", lambda: 7)

    with pytest.raises(SystemExit) as error:
        runpy.run_module("pagetrace.__main__", run_name="__main__")

    assert error.value.code == 7


def test_detection_read_failure_is_a_storage_error(tmp_path: Path) -> None:
    with pytest.raises(DocumentStorageError, match="staged"):
        detect_media_type(tmp_path / "missing.bin")


def test_store_root_must_be_a_directory(tmp_path: Path, image_factory: ImageFactory) -> None:
    source = image_factory(tmp_path / "image.png", image_format="PNG")
    store = tmp_path / "store"
    store.write_text("not a directory", encoding="utf-8")

    with pytest.raises(DocumentStorageError, match="initialize"):
        ingest_document(source, store=store)


def test_parser_format_must_match_detected_signature(
    tmp_path: Path,
    image_factory: ImageFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = image_factory(tmp_path / "image.jpg", image_format="JPEG")
    monkeypatch.setattr("pagetrace.documents.ingestion.detect_media_type", lambda _: MediaType.PNG)

    with pytest.raises(InvalidDocumentError, match="expected PNG"):
        ingest_document(source, store=tmp_path / "store")


def test_pillow_decompression_bomb_is_a_document_limit(
    tmp_path: Path,
    image_factory: ImageFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = image_factory(tmp_path / "image.png", image_format="PNG")

    def raise_bomb(_: object) -> None:
        raise Image.DecompressionBombError("test bomb")

    monkeypatch.setattr(Image, "open", raise_bomb)
    with pytest.raises(DocumentLimitError, match="Pillow"):
        ingest_document(source, store=tmp_path / "store")


def test_zero_page_pdf_is_rejected(tmp_path: Path, pdf_factory: PdfFactory) -> None:
    source = pdf_factory(tmp_path / "empty-pages.pdf", pages=0)

    with pytest.raises(InvalidDocumentError, match="one page"):
        ingest_document(source, store=tmp_path / "store")


def test_missing_stored_manifest_is_rejected(tmp_path: Path, image_factory: ImageFactory) -> None:
    source = image_factory(tmp_path / "image.png", image_format="PNG")
    store = tmp_path / "store"
    manifest = ingest_document(source, store=store)
    (store / "documents" / manifest.document_id / "manifest.json").unlink()

    with pytest.raises(DocumentIntegrityError, match="manifest is missing"):
        load_document(manifest.document_id, store=store)


def test_missing_stored_source_is_rejected(tmp_path: Path, image_factory: ImageFactory) -> None:
    source = image_factory(tmp_path / "image.png", image_format="PNG")
    store = tmp_path / "store"
    manifest = ingest_document(source, store=store)
    (store / "documents" / manifest.document_id / "source.png").unlink()

    with pytest.raises(DocumentIntegrityError, match="source is missing"):
        load_document(manifest.document_id, store=store)


def test_manifest_directory_identity_mismatch_is_rejected(
    tmp_path: Path, image_factory: ImageFactory
) -> None:
    source = image_factory(tmp_path / "image.png", image_format="PNG")
    store = tmp_path / "store"
    manifest = ingest_document(source, store=store)
    manifest_path = store / "documents" / manifest.document_id / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    different_fingerprint = "b" * 64
    different_id = f"sha256-{different_fingerprint}"
    payload["fingerprint"] = different_fingerprint
    payload["document_id"] = different_id
    payload["pages"][0]["page_id"] = f"{different_id}-page-000001"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DocumentIntegrityError, match="directory"):
        load_document(manifest.document_id, store=store)


def test_valid_but_conflicting_existing_manifest_is_not_overwritten(
    tmp_path: Path, image_factory: ImageFactory
) -> None:
    source = image_factory(tmp_path / "image.png", image_format="PNG")
    store = tmp_path / "store"
    manifest = ingest_document(source, store=store)
    conflicting = replace(
        manifest,
        document_metadata=DocumentMetadata(title="contradictory stored metadata"),
    )
    manifest_path = store / "documents" / manifest.document_id / "manifest.json"
    manifest_path.write_bytes(serialize_manifest(conflicting))

    with pytest.raises(DocumentIntegrityError, match="conflicts"):
        ingest_document(source, store=store)
    assert manifest_path.read_bytes() == serialize_manifest(conflicting)


def test_safe_open_failure_is_an_invalid_document(
    tmp_path: Path,
    image_factory: ImageFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = image_factory(tmp_path / "image.png", image_format="PNG")

    def fail_open(_: object, __: int) -> int:
        raise PermissionError("test denial")

    monkeypatch.setattr("pagetrace.documents.ingestion.os.open", fail_open)
    with pytest.raises(InvalidDocumentError, match="opened safely"):
        ingest_document(source, store=tmp_path / "store")


def test_streaming_limit_handles_growth_after_path_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "growing.bin"
    source.write_bytes(b"12")
    real_stat = source.lstat()

    def fake_lstat(path: Path) -> os.stat_result | SimpleNamespace:
        if path == source:
            return SimpleNamespace(
                st_mode=real_stat.st_mode,
                st_size=1,
                st_dev=real_stat.st_dev,
                st_ino=real_stat.st_ino,
                st_mtime_ns=real_stat.st_mtime_ns,
            )
        return Path.lstat(path)

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    with pytest.raises(DocumentLimitError, match="1-byte"):
        _stage_input(source, tmp_path / "staged.bin", IngestionLimits(max_file_bytes=1))


def test_source_mutation_is_detected_after_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "mutated.bin"
    source.write_bytes(b"12")
    real_stat = source.lstat()
    original_lstat = Path.lstat

    def fake_lstat(path: Path) -> os.stat_result | SimpleNamespace:
        if path == source:
            return SimpleNamespace(
                st_mode=real_stat.st_mode,
                st_size=3,
                st_dev=real_stat.st_dev,
                st_ino=real_stat.st_ino,
                st_mtime_ns=real_stat.st_mtime_ns,
            )
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    with pytest.raises(InvalidDocumentError, match="changed during"):
        _stage_input(source, tmp_path / "staged.bin", IngestionLimits(max_file_bytes=10))
