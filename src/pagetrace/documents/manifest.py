"""Deterministic JSON serialization for immutable document manifests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast

from pagetrace.documents.errors import DocumentIntegrityError
from pagetrace.documents.models import (
    DimensionUnit,
    DocumentManifest,
    DocumentMetadata,
    MediaType,
    PageManifest,
)

_DOCUMENT_FIELDS = {
    "schema_version",
    "document_id",
    "fingerprint_algorithm",
    "fingerprint",
    "media_type",
    "byte_size",
    "page_count",
    "document_metadata",
    "pages",
}
_METADATA_FIELDS = {
    "title",
    "author",
    "subject",
    "creator",
    "producer",
    "creation_date",
    "modification_date",
}
_PAGE_FIELDS = {
    "page_id",
    "page_number",
    "width",
    "height",
    "dimension_unit",
    "rotation_degrees",
}


def serialize_manifest(manifest: DocumentManifest) -> bytes:
    """Serialize a manifest to stable UTF-8 JSON with one final newline."""

    payload: dict[str, object] = {
        "schema_version": manifest.schema_version,
        "document_id": manifest.document_id,
        "fingerprint_algorithm": manifest.fingerprint_algorithm,
        "fingerprint": manifest.fingerprint,
        "media_type": manifest.media_type.value,
        "byte_size": manifest.byte_size,
        "page_count": manifest.page_count,
        "document_metadata": {
            "title": manifest.document_metadata.title,
            "author": manifest.document_metadata.author,
            "subject": manifest.document_metadata.subject,
            "creator": manifest.document_metadata.creator,
            "producer": manifest.document_metadata.producer,
            "creation_date": manifest.document_metadata.creation_date,
            "modification_date": manifest.document_metadata.modification_date,
        },
        "pages": [
            {
                "page_id": page.page_id,
                "page_number": page.page_number,
                "width": page.width,
                "height": page.height,
                "dimension_unit": page.dimension_unit.value,
                "rotation_degrees": page.rotation_degrees,
            }
            for page in manifest.pages
        ],
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{text}\n".encode()


def deserialize_manifest(data: bytes) -> DocumentManifest:
    """Parse and validate persisted manifest bytes without guessing schema changes."""

    try:
        value: object = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DocumentIntegrityError("manifest is not valid UTF-8 JSON") from exc

    document = _mapping(value, "manifest")
    _require_exact_fields(document, _DOCUMENT_FIELDS, "manifest")
    metadata_value = _mapping(document["document_metadata"], "document_metadata")
    _require_exact_fields(metadata_value, _METADATA_FIELDS, "document_metadata")
    pages_value = document["pages"]
    if not isinstance(pages_value, list):
        raise DocumentIntegrityError("pages must be a JSON array")

    try:
        metadata = DocumentMetadata(
            title=_optional_string(metadata_value["title"], "title"),
            author=_optional_string(metadata_value["author"], "author"),
            subject=_optional_string(metadata_value["subject"], "subject"),
            creator=_optional_string(metadata_value["creator"], "creator"),
            producer=_optional_string(metadata_value["producer"], "producer"),
            creation_date=_optional_string(metadata_value["creation_date"], "creation_date"),
            modification_date=_optional_string(
                metadata_value["modification_date"], "modification_date"
            ),
        )
        pages = tuple(_parse_page(item) for item in pages_value)
        return DocumentManifest(
            schema_version=_integer(document["schema_version"], "schema_version"),
            document_id=_string(document["document_id"], "document_id"),
            fingerprint_algorithm=_string(
                document["fingerprint_algorithm"], "fingerprint_algorithm"
            ),
            fingerprint=_string(document["fingerprint"], "fingerprint"),
            media_type=MediaType(_string(document["media_type"], "media_type")),
            byte_size=_integer(document["byte_size"], "byte_size"),
            page_count=_integer(document["page_count"], "page_count"),
            document_metadata=metadata,
            pages=pages,
        )
    except (TypeError, ValueError) as exc:
        raise DocumentIntegrityError(f"invalid manifest value: {exc}") from exc


def _parse_page(value: object) -> PageManifest:
    page = _mapping(value, "page")
    _require_exact_fields(page, _PAGE_FIELDS, "page")
    rotation_value = page["rotation_degrees"]
    rotation = None if rotation_value is None else _integer(rotation_value, "rotation_degrees")
    return PageManifest(
        page_id=_string(page["page_id"], "page_id"),
        page_number=_integer(page["page_number"], "page_number"),
        width=_number(page["width"], "width"),
        height=_number(page["height"], "height"),
        dimension_unit=DimensionUnit(_string(page["dimension_unit"], "dimension_unit")),
        rotation_degrees=rotation,
    )


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise DocumentIntegrityError(f"{name} must be a JSON object with string keys")
    return cast(dict[str, object], value)


def _require_exact_fields(value: Mapping[str, object], expected: set[str], name: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise DocumentIntegrityError(
            f"{name} fields are invalid; missing={missing}, unexpected={unexpected}"
        )


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise DocumentIntegrityError(f"{name} must be a string")
    return value


def _optional_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _string(value, name)


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DocumentIntegrityError(f"{name} must be an integer")
    return value


def _number(value: object, name: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DocumentIntegrityError(f"{name} must be a number")
    return value
