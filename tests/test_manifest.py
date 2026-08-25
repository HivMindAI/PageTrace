from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import FrozenInstanceError, replace
from typing import cast

import pytest

from pagetrace.documents import (
    DimensionUnit,
    DocumentIntegrityError,
    DocumentManifest,
    DocumentMetadata,
    IngestionLimits,
    MediaType,
    PageManifest,
    deserialize_manifest,
    serialize_manifest,
)
from pagetrace.documents.models import document_id_for, page_id_for


def _manifest() -> DocumentManifest:
    fingerprint = "a" * 64
    document_id = document_id_for(fingerprint)
    page = PageManifest(
        page_id=page_id_for(document_id, 1),
        page_number=1,
        width=10,
        height=20,
        dimension_unit=DimensionUnit.PIXELS,
        rotation_degrees=None,
    )
    return DocumentManifest(
        schema_version=1,
        document_id=document_id,
        fingerprint_algorithm="sha256",
        fingerprint=fingerprint,
        media_type=MediaType.PNG,
        byte_size=100,
        page_count=1,
        document_metadata=DocumentMetadata(title="deterministic"),
        pages=(page,),
    )


def test_manifest_serialization_is_stable_utf8_json() -> None:
    manifest = _manifest()

    first = serialize_manifest(manifest)
    second = serialize_manifest(manifest)

    assert first == second
    assert first.endswith(b"\n")
    assert deserialize_manifest(first) == manifest
    assert list(json.loads(first)) == sorted(json.loads(first))


@pytest.mark.parametrize("value", [0, -1, True])
def test_ingestion_limits_require_positive_integers(value: int) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        IngestionLimits(max_file_bytes=value)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(schema_version=99),
        lambda payload: payload.update(fingerprint="A" * 64),
        lambda payload: payload.update(document_id=f"sha256-{'b' * 64}"),
        lambda payload: payload.update(page_count=2),
        lambda payload: payload.update(media_type="application/zip"),
        lambda payload: payload.pop("pages"),
        lambda payload: payload.update(extra="field"),
        lambda payload: payload.update(pages="not an array"),
    ],
)
def test_manifest_deserialization_rejects_invalid_structure(mutation: object) -> None:
    payload = json.loads(serialize_manifest(_manifest()))
    callable_mutation = mutation
    assert callable(callable_mutation)
    callable_mutation(payload)

    with pytest.raises(DocumentIntegrityError):
        deserialize_manifest(json.dumps(payload).encode())


@pytest.mark.parametrize("data", [b"not json", b"\xff", b"[]"])
def test_manifest_deserialization_rejects_invalid_json_or_root(data: bytes) -> None:
    with pytest.raises(DocumentIntegrityError):
        deserialize_manifest(data)


def test_manifest_pages_are_frozen() -> None:
    manifest = _manifest()

    with pytest.raises(FrozenInstanceError):
        _assign_attribute(manifest, "document_id", "changed")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda page: replace(page, page_number=0),
        lambda page: replace(page, width=0),
        lambda page: replace(page, height=float("inf")),
        lambda page: replace(page, rotation_degrees=45),
    ],
)
def test_page_manifest_rejects_invalid_values(
    mutation: Callable[[PageManifest], PageManifest],
) -> None:
    with pytest.raises(ValueError, match="must be"):
        mutation(_manifest().pages[0])


def test_identity_helpers_reject_unsafe_values() -> None:
    with pytest.raises(ValueError, match="fingerprint"):
        document_id_for("short")
    with pytest.raises(ValueError, match="document_id"):
        page_id_for("../unsafe", 1)
    with pytest.raises(ValueError, match="page_number"):
        page_id_for(f"sha256-{'a' * 64}", 0)


def test_document_manifest_rejects_inconsistent_core_values() -> None:
    manifest = _manifest()

    with pytest.raises(ValueError, match="algorithm"):
        replace(manifest, fingerprint_algorithm="md5")
    with pytest.raises(ValueError, match="byte_size"):
        replace(manifest, byte_size=0)
    with pytest.raises(ValueError, match="immutable tuple"):
        replace(manifest, pages=cast(tuple[PageManifest, ...], []))


def test_document_manifest_rejects_inconsistent_page_values() -> None:
    manifest = _manifest()
    page = manifest.pages[0]

    with pytest.raises(ValueError, match="numbering"):
        replace(manifest, pages=(replace(page, page_number=2),))
    with pytest.raises(ValueError, match="page_id"):
        replace(manifest, pages=(replace(page, page_id="wrong"),))
    with pytest.raises(ValueError, match="dimension unit"):
        replace(manifest, pages=(replace(page, dimension_unit=DimensionUnit.POINTS),))
    with pytest.raises(ValueError, match="rotation"):
        replace(manifest, pages=(replace(page, rotation_degrees=90),))

    second_page = replace(
        page,
        page_id=page_id_for(manifest.document_id, 2),
        page_number=2,
    )
    with pytest.raises(ValueError, match="exactly one"):
        replace(manifest, page_count=2, pages=(page, second_page))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(document_metadata=[]),
        lambda payload: payload["document_metadata"].update(title=7),
        lambda payload: payload.update(schema_version=True),
        lambda payload: payload["pages"][0].update(width=True),
    ],
)
def test_manifest_deserialization_rejects_wrong_json_value_types(mutation: object) -> None:
    payload = json.loads(serialize_manifest(_manifest()))
    callable_mutation = mutation
    assert callable(callable_mutation)
    callable_mutation(payload)

    with pytest.raises(DocumentIntegrityError):
        deserialize_manifest(json.dumps(payload).encode())


def _assign_attribute(value: object, name: str, replacement: object) -> None:
    setattr(value, name, replacement)
