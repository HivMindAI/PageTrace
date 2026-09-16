from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import pagetrace.structure.storage as structure_storage
from pagetrace.documents import DimensionUnit, MediaType, ingest_document
from pagetrace.extraction import extract_document_text
from pagetrace.ocr import ocr_document
from pagetrace.ocr.engine import OcrEngineResult
from pagetrace.structure import (
    StructuredDocumentArtifact,
    StructureIntegrityError,
    StructureStorageError,
    deserialize_structured_document,
    load_structured_document,
    serialize_structured_document,
    structure_content_fingerprint_for,
    structure_document,
)
from pagetrace.structure.storage import persist_structured_document
from tests.conftest import ImageFactory
from tests.test_ocr import _descriptor, _install_fake_runtime
from tests.test_structure import _ReplayEngine


def test_deserializer_rejects_malformed_and_noncanonical_values() -> None:
    with pytest.raises(StructureIntegrityError, match="UTF-8 JSON"):
        deserialize_structured_document(b"not json")
    with pytest.raises(StructureIntegrityError, match="fields are invalid"):
        deserialize_structured_document(b"{}")


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("mapping", "JSON object"),
        ("array", "JSON array"),
        ("string", "must be a string"),
        ("integer", "must be an integer"),
        ("number", "finite number"),
    ],
)
def test_deserializer_rejects_wrong_json_types(case: str, message: str) -> None:
    from tests.test_structure_models import _artifact

    payload = json.loads(serialize_structured_document(_artifact()))
    if case == "mapping":
        payload["processor"] = []
    elif case == "array":
        payload["pages"] = {}
    elif case == "string":
        payload["artifact_id"] = 1
    elif case == "integer":
        payload["page_count"] = 1.0
    else:
        payload["pages"][0]["width"] = "wide"

    with pytest.raises(StructureIntegrityError, match=message):
        deserialize_structured_document(json.dumps(payload).encode())


def test_load_rejects_unsafe_and_missing_artifact_ids(tmp_path: Path) -> None:
    document_id = f"sha256-{'1' * 64}"

    with pytest.raises(StructureIntegrityError, match="safe structure"):
        load_structured_document("../artifact", document_id=document_id, store=tmp_path)
    with pytest.raises(StructureIntegrityError, match="document_id"):
        load_structured_document(
            f"structure-sha256-{'2' * 64}",
            document_id="../document",
            store=tmp_path,
        )
    with pytest.raises(StructureStorageError, match="does not exist"):
        load_structured_document(
            f"structure-sha256-{'2' * 64}",
            document_id=document_id,
            store=tmp_path,
        )


def test_tampered_structured_artifact_fails_readback(
    tmp_path: Path,
    image_factory: ImageFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "store"
    artifact = _create_image_artifact(store, tmp_path, image_factory, monkeypatch)
    path = (
        store
        / "documents"
        / artifact.document_id
        / "artifacts"
        / "structure"
        / f"{artifact.artifact_id}.json"
    )
    path.write_bytes(path.read_bytes().replace(b"PageTrace", b"PageTracz"))

    with pytest.raises(StructureIntegrityError, match="content_fingerprint"):
        load_structured_document(
            artifact.artifact_id,
            document_id=artifact.document_id,
            store=store,
        )


def test_existing_artifact_must_equal_deterministic_output(
    tmp_path: Path,
    image_factory: ImageFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "store"
    artifact = _create_image_artifact(store, tmp_path, image_factory, monkeypatch)
    span = replace(artifact.pages[0].spans[0], text="different")
    page = replace(artifact.pages[0], spans=(span,))
    pages = (page,)
    contradiction = replace(
        artifact,
        pages=pages,
        content_fingerprint=structure_content_fingerprint_for(pages),
    )

    with pytest.raises(StructureIntegrityError, match="contradicts"):
        persist_structured_document(contradiction, store=store)

    assert persist_structured_document(artifact, store=store) == artifact


def test_readback_rejects_oversized_and_misnamed_artifacts(
    tmp_path: Path,
    image_factory: ImageFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "store"
    artifact = _create_image_artifact(store, tmp_path, image_factory, monkeypatch)
    directory = store / "documents" / artifact.document_id / "artifacts" / "structure"
    original = directory / f"{artifact.artifact_id}.json"
    other_id = f"structure-sha256-{'f' * 64}"
    (directory / f"{other_id}.json").write_bytes(original.read_bytes())

    with pytest.raises(StructureIntegrityError, match="filename"):
        load_structured_document(other_id, document_id=artifact.document_id, store=store)

    monkeypatch.setattr(structure_storage, "_MAX_STRUCTURE_ARTIFACT_BYTES", 1)
    with pytest.raises(StructureIntegrityError, match="size limit"):
        load_structured_document(
            artifact.artifact_id,
            document_id=artifact.document_id,
            store=store,
        )
    original.unlink()
    with pytest.raises(StructureIntegrityError, match="persistence size limit"):
        persist_structured_document(artifact, store=store)
    assert not original.exists()


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("document", "document"),
        ("text", "text provenance"),
        ("ocr", "OCR provenance"),
        ("lineage", "share provenance"),
        ("page_count", "page count"),
        ("page_ids", "page identities"),
        ("unit", "page unit"),
        ("rotation", "page rotation"),
        ("dimensions", "page dimensions"),
        ("backend", "layout backend"),
    ],
)
def test_provenance_validation_rejects_cross_stage_contradictions(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    message: str,
) -> None:
    from tests.test_structure_models import _artifact

    artifact = _artifact()
    manifest = SimpleNamespace(
        fingerprint=artifact.document_fingerprint,
        page_count=artifact.page_count,
        pages=tuple(
            SimpleNamespace(
                page_id=page.page_id,
                width=page.width,
                height=page.height,
                dimension_unit=page.dimension_unit,
                rotation_degrees=page.source_rotation_degrees,
            )
            for page in artifact.pages
        ),
        media_type=MediaType.PDF,
    )
    text = SimpleNamespace(
        artifact_id=artifact.source_text_artifact_id,
        content_fingerprint=artifact.source_text_content_fingerprint,
    )
    ocr = SimpleNamespace(
        source_text_artifact_id=artifact.source_text_artifact_id,
        content_fingerprint=artifact.source_ocr_content_fingerprint,
    )
    if case == "document":
        manifest.fingerprint = "0" * 64
    elif case == "text":
        text.content_fingerprint = "0" * 64
    elif case == "ocr":
        ocr.content_fingerprint = "0" * 64
    elif case == "lineage":
        ocr.source_text_artifact_id = f"text-sha256-{'0' * 64}"
    elif case == "page_count":
        manifest.page_count = 2
    elif case == "page_ids":
        manifest.pages = (SimpleNamespace(page_id="wrong"),)
    elif case == "unit":
        manifest.pages[0].dimension_unit = DimensionUnit.PIXELS
    elif case == "rotation":
        manifest.pages[0].rotation_degrees = 90
    elif case == "dimensions":
        manifest.pages[0].width = 201
    else:
        manifest.media_type = MediaType.PNG
    monkeypatch.setattr(structure_storage, "load_document", lambda *_args, **_kwargs: manifest)
    monkeypatch.setattr(structure_storage, "load_text_extraction", lambda *_args, **_kwargs: text)
    monkeypatch.setattr(structure_storage, "load_ocr_artifact", lambda *_args, **_kwargs: ocr)

    with pytest.raises(StructureIntegrityError, match=message):
        structure_storage._validate_provenance(artifact, store=Path("unused"))


def _create_image_artifact(
    store: Path,
    tmp_path: Path,
    image_factory: ImageFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> StructuredDocumentArtifact:
    source = image_factory(tmp_path / "page.png", image_format="PNG", size=(100, 80))
    manifest = ingest_document(source, store=store)
    text_artifact = extract_document_text(manifest.document_id, store=store)
    _install_fake_runtime(
        monkeypatch,
        manifest.media_type,
        (OcrEngineResult(("PageTrace",), (0.9,)),),
    )
    ocr_artifact = ocr_document(manifest.document_id, text_artifact.artifact_id, store=store)
    replay = OcrEngineResult(
        ("PageTrace",),
        (0.9,),
        (((10, 10), (90, 10), (90, 70), (10, 70)),),
    )
    monkeypatch.setattr(
        "pagetrace.structure.processing.current_ocr_processor_descriptor",
        lambda _media_type: _descriptor(MediaType.PNG),
    )
    monkeypatch.setattr(
        "pagetrace.structure.processing.create_ocr_engine",
        lambda _configuration: _ReplayEngine(replay),
    )
    return structure_document(
        manifest.document_id,
        text_artifact.artifact_id,
        ocr_artifact.artifact_id,
        store=store,
    )
