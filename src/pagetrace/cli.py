"""Minimal command-line interface for ingestion and verified inspection."""

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


def build_parser() -> argparse.ArgumentParser:
    """Build the public PageTrace argument parser."""

    parser = argparse.ArgumentParser(prog="pagetrace", description="PageTrace document ingestion")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="validate and persist a document")
    ingest_parser.add_argument("file", type=Path, help="input PDF, PNG, or JPEG path")
    ingest_parser.add_argument("--store", type=Path, default=Path(".pagetrace"))
    ingest_parser.add_argument("--json", action="store_true", help="emit the canonical manifest")

    inspect_parser = subparsers.add_parser("inspect", help="verify and inspect a stored document")
    inspect_parser.add_argument("document_id", help="canonical PageTrace document identifier")
    inspect_parser.add_argument("--store", type=Path, default=Path(".pagetrace"))
    inspect_parser.add_argument("--json", action="store_true", help="emit the canonical manifest")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI, returning a process status for expected document errors."""

    arguments = build_parser().parse_args(argv)
    try:
        if arguments.command == "ingest":
            manifest = ingest_document(arguments.file, store=arguments.store)
        else:
            manifest = load_document(arguments.document_id, store=arguments.store)
    except DocumentError as exc:
        print(f"pagetrace: error: {exc}", file=sys.stderr)
        return 2

    _print_manifest(manifest, as_json=arguments.json)
    return 0


def _print_manifest(manifest: DocumentManifest, *, as_json: bool) -> None:
    if as_json:
        sys.stdout.buffer.write(serialize_manifest(manifest))
        return
    print(f"document id: {manifest.document_id}")
    print(f"SHA-256: {manifest.fingerprint}")
    print(f"media type: {manifest.media_type.value}")
    print(f"page count: {manifest.page_count}")
