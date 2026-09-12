"""Command-line interface for ingestion and deterministic text extraction."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pagetrace.documents import (
    DocumentError,
    DocumentManifest,
    ingest_document,
    load_document,
    serialize_manifest,
)
from pagetrace.extraction import (
    ExtractionError,
    TextExtractionArtifact,
    extract_document_text,
    load_text_extraction,
    serialize_text_extraction,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the public PageTrace argument parser."""

    parser = argparse.ArgumentParser(
        prog="pagetrace", description="PageTrace deterministic document processing"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="validate and persist a document")
    ingest_parser.add_argument("file", type=Path, help="input PDF, PNG, or JPEG path")
    ingest_parser.add_argument("--store", type=Path, default=Path(".pagetrace"))
    ingest_parser.add_argument("--json", action="store_true", help="emit the canonical manifest")

    inspect_parser = subparsers.add_parser("inspect", help="verify and inspect a stored document")
    inspect_parser.add_argument("document_id", help="canonical PageTrace document identifier")
    inspect_parser.add_argument("--store", type=Path, default=Path(".pagetrace"))
    inspect_parser.add_argument("--json", action="store_true", help="emit the canonical manifest")

    extract_parser = subparsers.add_parser(
        "extract-text", help="extract embedded PDF text and route OCR candidates"
    )
    extract_parser.add_argument("document_id", help="verified PageTrace document identifier")
    extract_parser.add_argument("--store", type=Path, default=Path(".pagetrace"))
    extract_parser.add_argument(
        "--json", action="store_true", help="emit the canonical text artifact"
    )

    inspect_text_parser = subparsers.add_parser(
        "inspect-text", help="verify and inspect a stored text artifact"
    )
    inspect_text_parser.add_argument("document_id", help="verified PageTrace document identifier")
    inspect_text_parser.add_argument("artifact_id", help="canonical text artifact identifier")
    inspect_text_parser.add_argument("--store", type=Path, default=Path(".pagetrace"))
    inspect_text_parser.add_argument(
        "--json", action="store_true", help="emit the canonical text artifact"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI, returning a process status for expected domain errors."""

    arguments = build_parser().parse_args(argv)
    try:
        if arguments.command == "ingest":
            manifest = ingest_document(arguments.file, store=arguments.store)
            _print_manifest(manifest, as_json=arguments.json)
        elif arguments.command == "inspect":
            manifest = load_document(arguments.document_id, store=arguments.store)
            _print_manifest(manifest, as_json=arguments.json)
        elif arguments.command == "extract-text":
            artifact = extract_document_text(arguments.document_id, store=arguments.store)
            _print_text_extraction(artifact, as_json=arguments.json)
        else:
            artifact = load_text_extraction(
                arguments.artifact_id,
                document_id=arguments.document_id,
                store=arguments.store,
            )
            _print_text_extraction(artifact, as_json=arguments.json)
    except (DocumentError, ExtractionError) as exc:
        print(f"pagetrace: error: {exc}", file=sys.stderr)
        return 2
    return 0


def _print_manifest(manifest: DocumentManifest, *, as_json: bool) -> None:
    if as_json:
        sys.stdout.buffer.write(serialize_manifest(manifest))
        return
    print(f"document id: {manifest.document_id}")
    print(f"SHA-256: {manifest.fingerprint}")
    print(f"media type: {manifest.media_type.value}")
    print(f"page count: {manifest.page_count}")


def _print_text_extraction(artifact: TextExtractionArtifact, *, as_json: bool) -> None:
    if as_json:
        sys.stdout.buffer.write(serialize_text_extraction(artifact))
        return
    print(f"text artifact id: {artifact.artifact_id}")
    print(f"document id: {artifact.document_id}")
    print(f"document SHA-256: {artifact.document_fingerprint}")
    print(f"extractor: {artifact.extractor.name} {artifact.extractor.version}")
    print(
        f"PDF backend: {artifact.extractor.pdf_backend_name} "
        f"{artifact.extractor.pdf_backend_version}"
    )
    print(f"page count: {artifact.page_count}")
    for page in artifact.pages:
        print(
            f"page {page.page_number}: {page.status.value} "
            f"({page.non_whitespace_character_count} non-whitespace characters)"
        )
