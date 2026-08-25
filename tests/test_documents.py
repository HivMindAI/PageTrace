from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from PIL import Image

from pagetrace.documents import (
    DimensionUnit,
    DocumentIntegrityError,
    DocumentLimitError,
    DocumentStorageError,
    EncryptedDocumentError,
    IngestionLimits,
    InvalidDocumentError,
    MediaType,
    UnsupportedDocumentError,
    ingest_document,
    load_document,
)
from tests.conftest import ImageFactory, PdfFactory


def test_valid_pdf_records_pages_rotation_and_whitelisted_metadata(
    tmp_path: Path, pdf_factory: PdfFactory
) -> None:
    source = pdf_factory(
        tmp_path / "document.pdf",
        pages=2,
        rotation=90,
        metadata={
            "/Title": "A deterministic PDF",
            "/Author": "PageTrace",
            "/Subject": "Ingestion",
            "/Creator": "tests",
            "/Producer": "pypdf",
            "/CreationDate": "D:20260101000000Z",
            "/ModDate": "D:20260102000000Z",
            "/Ignored": "not persisted",
        },
    )

    manifest = ingest_document(source, store=tmp_path / "store")

    assert manifest.media_type is MediaType.PDF
    assert manifest.page_count == 2
    assert [page.page_number for page in manifest.pages] == [1, 2]
    assert len({page.page_id for page in manifest.pages}) == 2
    assert all(page.dimension_unit is DimensionUnit.POINTS for page in manifest.pages)
    assert all(page.rotation_degrees == 90 for page in manifest.pages)
    assert all((page.width, page.height) == (72.0, 144.0) for page in manifest.pages)
    assert manifest.document_metadata.title == "A deterministic PDF"
    assert manifest.document_metadata.author == "PageTrace"
    assert manifest.document_metadata.modification_date == "D:20260102000000Z"
    assert not hasattr(manifest.document_metadata, "ignored")


@pytest.mark.parametrize(
    ("image_format", "extension", "media_type"),
    [("PNG", ".png", MediaType.PNG), ("JPEG", ".jpg", MediaType.JPEG)],
)
def test_valid_image_records_one_pixel_page(
    tmp_path: Path,
    image_factory: ImageFactory,
    image_format: str,
    extension: str,
    media_type: MediaType,
) -> None:
    source = image_factory(tmp_path / f"image{extension}", image_format=image_format, size=(7, 5))

    manifest = ingest_document(source, store=tmp_path / "store")

    assert manifest.media_type is media_type
    assert manifest.page_count == 1
    assert manifest.pages[0].width == 7
    assert manifest.pages[0].height == 5
    assert manifest.pages[0].dimension_unit is DimensionUnit.PIXELS
    assert manifest.pages[0].rotation_degrees is None


def test_content_detection_ignores_misleading_extension(
    tmp_path: Path, pdf_factory: PdfFactory
) -> None:
    source = pdf_factory(tmp_path / "report.txt")

    manifest = ingest_document(source, store=tmp_path / "store")

    assert manifest.media_type is MediaType.PDF
    assert (tmp_path / "store" / "documents" / manifest.document_id / "source.pdf").is_file()


def test_byte_identical_paths_have_identical_manifests(
    tmp_path: Path, image_factory: ImageFactory
) -> None:
    first = image_factory(tmp_path / "first.png", image_format="PNG")
    second = tmp_path / "nested" / "second.bin"
    second.parent.mkdir()
    second.write_bytes(first.read_bytes())

    first_manifest = ingest_document(first, store=tmp_path / "first-store")
    second_manifest = ingest_document(second, store=tmp_path / "second-store")

    expected_fingerprint = hashlib.sha256(first.read_bytes()).hexdigest()
    assert first_manifest.fingerprint == expected_fingerprint
    assert first_manifest == second_manifest
    assert first_manifest.document_id == f"sha256-{expected_fingerprint}"
    assert first_manifest.pages[0].page_id == second_manifest.pages[0].page_id


def test_reingestion_is_idempotent(tmp_path: Path, image_factory: ImageFactory) -> None:
    source = image_factory(tmp_path / "image.png", image_format="PNG")
    store = tmp_path / "store"

    first = ingest_document(source, store=store)
    second = ingest_document(source, store=store)

    assert first == second
    artifact_directories = list((store / "documents").iterdir())
    assert artifact_directories == [store / "documents" / first.document_id]


def test_readback_returns_equal_immutable_manifest(tmp_path: Path, pdf_factory: PdfFactory) -> None:
    source = pdf_factory(tmp_path / "document.pdf")
    store = tmp_path / "store"
    manifest = ingest_document(source, store=store)

    loaded = load_document(manifest.document_id, store=store)

    assert loaded == manifest
    with pytest.raises(AttributeError):
        _assign_attribute(loaded, "page_count", 10)
    with pytest.raises(AttributeError):
        _assign_attribute(loaded.pages[0], "page_number", 2)


@pytest.mark.parametrize(
    "content",
    [b"plain text", b"\x00\x01arbitrary binary", b"GIF89a"],
)
def test_unsupported_content_is_rejected(tmp_path: Path, content: bytes) -> None:
    source = tmp_path / "unsupported.bin"
    source.write_bytes(content)

    with pytest.raises(UnsupportedDocumentError):
        ingest_document(source, store=tmp_path / "store")


def test_empty_file_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "empty.pdf"
    source.touch()

    with pytest.raises(InvalidDocumentError, match="empty"):
        ingest_document(source, store=tmp_path / "store")


@pytest.mark.parametrize(
    "content",
    [b"%PDF-1.7\nnot a PDF", b"\x89PNG\r\n\x1a\nnot a PNG", b"\xff\xd8\xffnot a JPEG"],
)
def test_signature_without_valid_parser_content_is_rejected(tmp_path: Path, content: bytes) -> None:
    source = tmp_path / "malformed.bin"
    source.write_bytes(content)

    with pytest.raises(InvalidDocumentError):
        ingest_document(source, store=tmp_path / "store")


def test_encrypted_pdf_is_rejected(tmp_path: Path, pdf_factory: PdfFactory) -> None:
    source = pdf_factory(tmp_path / "encrypted.pdf", encrypted=True)

    with pytest.raises(EncryptedDocumentError, match="encrypted"):
        ingest_document(source, store=tmp_path / "store")


def test_file_size_limit_is_enforced(tmp_path: Path, image_factory: ImageFactory) -> None:
    source = image_factory(tmp_path / "image.png", image_format="PNG")
    limits = IngestionLimits(max_file_bytes=source.stat().st_size - 1)

    with pytest.raises(DocumentLimitError, match="byte"):
        ingest_document(source, store=tmp_path / "store", limits=limits)


def test_pdf_page_limit_is_enforced(tmp_path: Path, pdf_factory: PdfFactory) -> None:
    source = pdf_factory(tmp_path / "two-pages.pdf", pages=2)
    limits = IngestionLimits(max_pdf_pages=1)

    with pytest.raises(DocumentLimitError, match="1-page"):
        ingest_document(source, store=tmp_path / "store", limits=limits)


def test_image_pixel_limit_is_enforced(tmp_path: Path, image_factory: ImageFactory) -> None:
    source = image_factory(tmp_path / "image.jpg", image_format="JPEG", size=(4, 3))
    limits = IngestionLimits(max_image_pixels=11)

    with pytest.raises(DocumentLimitError, match="11-pixel"):
        ingest_document(source, store=tmp_path / "store", limits=limits)


def test_directory_input_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "directory"
    source.mkdir()

    with pytest.raises(InvalidDocumentError, match="regular file"):
        ingest_document(source, store=tmp_path / "store")


def test_missing_input_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(InvalidDocumentError, match="does not exist"):
        ingest_document(tmp_path / "missing.pdf", store=tmp_path / "store")


def test_symbolic_link_input_is_rejected(tmp_path: Path, image_factory: ImageFactory) -> None:
    target = image_factory(tmp_path / "target.png", image_format="PNG")
    link = tmp_path / "link.png"
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"platform does not permit test symlink creation: {exc}")

    with pytest.raises(InvalidDocumentError, match="symbolic-link"):
        ingest_document(link, store=tmp_path / "store")


@pytest.mark.parametrize("document_id", ["../escape", "..\\escape", "sha256-not-a-hash", ""])
def test_unsafe_document_id_cannot_escape_store(tmp_path: Path, document_id: str) -> None:
    with pytest.raises(DocumentIntegrityError, match="safe canonical"):
        load_document(document_id, store=tmp_path / "store")


def test_corrupted_manifest_is_rejected(tmp_path: Path, image_factory: ImageFactory) -> None:
    source = image_factory(tmp_path / "image.png", image_format="PNG")
    store = tmp_path / "store"
    manifest = ingest_document(source, store=store)
    path = store / "documents" / manifest.document_id / "manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = 2
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DocumentIntegrityError, match="schema version"):
        load_document(manifest.document_id, store=store)


def test_source_size_mismatch_is_rejected(tmp_path: Path, image_factory: ImageFactory) -> None:
    source = image_factory(tmp_path / "image.png", image_format="PNG")
    store = tmp_path / "store"
    manifest = ingest_document(source, store=store)
    stored_source = store / "documents" / manifest.document_id / "source.png"
    stored_source.write_bytes(stored_source.read_bytes() + b"tampered")

    with pytest.raises(DocumentIntegrityError, match="byte size"):
        load_document(manifest.document_id, store=store)


def test_source_fingerprint_mismatch_is_rejected(
    tmp_path: Path, image_factory: ImageFactory
) -> None:
    first = image_factory(tmp_path / "first.png", image_format="PNG", size=(4, 3))
    second = image_factory(tmp_path / "second.png", image_format="PNG", size=(4, 3))
    second_bytes = bytearray(second.read_bytes())
    second_bytes[-1] ^= 1
    second.write_bytes(second_bytes)
    assert first.stat().st_size == second.stat().st_size
    store = tmp_path / "store"
    manifest = ingest_document(first, store=store)
    stored_source = store / "documents" / manifest.document_id / "source.png"
    stored_source.write_bytes(second.read_bytes())

    with pytest.raises(DocumentIntegrityError, match="fingerprint"):
        load_document(manifest.document_id, store=store)


def test_corrupt_existing_artifact_is_not_overwritten(
    tmp_path: Path, image_factory: ImageFactory
) -> None:
    source = image_factory(tmp_path / "image.png", image_format="PNG")
    store = tmp_path / "store"
    manifest = ingest_document(source, store=store)
    manifest_path = store / "documents" / manifest.document_id / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")

    with pytest.raises(DocumentIntegrityError):
        ingest_document(source, store=store)
    assert manifest_path.read_text(encoding="utf-8") == "{}"


def test_failed_ingestion_cleans_staging(tmp_path: Path) -> None:
    source = tmp_path / "unsupported.txt"
    source.write_text("not a supported document", encoding="utf-8")
    store = tmp_path / "store"

    with pytest.raises(UnsupportedDocumentError):
        ingest_document(source, store=store)

    assert list((store / ".staging").iterdir()) == []
    assert list((store / "documents").iterdir()) == []


def test_multiframe_png_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "animated.png"
    first = Image.new("RGB", (2, 2), "red")
    second = Image.new("RGB", (2, 2), "blue")
    first.save(source, format="PNG", save_all=True, append_images=[second], duration=100)

    with pytest.raises(UnsupportedDocumentError, match="multi-frame"):
        ingest_document(source, store=tmp_path / "store")


def test_missing_stored_document_has_clear_error(tmp_path: Path) -> None:
    document_id = f"sha256-{'0' * 64}"

    with pytest.raises(DocumentStorageError, match="does not exist"):
        load_document(document_id, store=tmp_path / "store")


def test_stored_source_symlink_is_rejected(tmp_path: Path, image_factory: ImageFactory) -> None:
    source = image_factory(tmp_path / "image.png", image_format="PNG")
    store = tmp_path / "store"
    manifest = ingest_document(source, store=store)
    stored_source = store / "documents" / manifest.document_id / "source.png"
    replacement = tmp_path / "replacement.png"
    replacement.write_bytes(stored_source.read_bytes())
    stored_source.unlink()
    try:
        stored_source.symlink_to(replacement)
    except OSError as exc:
        pytest.skip(f"platform does not permit test symlink creation: {exc}")

    with pytest.raises(DocumentIntegrityError, match="missing or unsafe"):
        load_document(manifest.document_id, store=store)


def test_default_store_layout_uses_only_detected_type(
    tmp_path: Path, image_factory: ImageFactory
) -> None:
    source = image_factory(tmp_path / ".. malicious name .pdf", image_format="JPEG")
    store = tmp_path / "store"

    manifest = ingest_document(source, store=store)
    files = sorted(path.name for path in (store / "documents" / manifest.document_id).iterdir())

    assert files == ["manifest.json", "source.jpg"]
    assert os.path.commonpath(
        [store.resolve(), (store / "documents" / manifest.document_id).resolve()]
    ) == str(store.resolve())


def _assign_attribute(value: object, name: str, replacement: object) -> None:
    setattr(value, name, replacement)
