"""Command-line interface for deterministic PageTrace document processing."""

from __future__ import annotations

import argparse
import stat
import sys
from collections.abc import Sequence
from pathlib import Path

from pagetrace.corpus import (
    CorpusArtifact,
    CorpusError,
    build_corpus,
    load_corpus_artifact,
    serialize_corpus_artifact,
)
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
from pagetrace.ocr import (
    OcrArtifact,
    OcrConfig,
    OcrError,
    OcrEvaluation,
    OcrEvaluationError,
    OcrRoutingPolicy,
    evaluate_ocr,
    load_ocr_artifact,
    ocr_document,
    serialize_ocr_artifact,
    serialize_ocr_evaluation,
)
from pagetrace.structure import (
    StructuredDocumentArtifact,
    StructureError,
    load_structured_document,
    serialize_structured_document,
    structure_document,
)

_MAX_EVALUATION_TEXT_BYTES = 20 * 1024 * 1024


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

    ocr_parser = subparsers.add_parser(
        "ocr", help="run OCR only on pages selected by a text-routing artifact"
    )
    ocr_parser.add_argument("document_id", help="verified PageTrace document identifier")
    ocr_parser.add_argument("text_artifact_id", help="verified text-routing artifact identifier")
    ocr_parser.add_argument("--store", type=Path, default=Path(".pagetrace"))
    ocr_parser.add_argument(
        "--candidates-only",
        action="store_true",
        help="exclude sparse embedded-text pages from OCR",
    )
    ocr_parser.add_argument("--json", action="store_true", help="emit the canonical OCR artifact")

    inspect_ocr_parser = subparsers.add_parser(
        "inspect-ocr", help="verify and inspect a stored OCR artifact"
    )
    inspect_ocr_parser.add_argument("document_id", help="verified PageTrace document identifier")
    inspect_ocr_parser.add_argument("artifact_id", help="canonical OCR artifact identifier")
    inspect_ocr_parser.add_argument("--store", type=Path, default=Path(".pagetrace"))
    inspect_ocr_parser.add_argument(
        "--json", action="store_true", help="emit the canonical OCR artifact"
    )

    evaluate_parser = subparsers.add_parser(
        "evaluate-ocr", help="measure exact OCR text against a UTF-8 reference"
    )
    evaluate_parser.add_argument("reference", type=Path, help="reference UTF-8 text file")
    evaluate_parser.add_argument("prediction", type=Path, help="predicted UTF-8 text file")
    evaluate_parser.add_argument("--json", action="store_true", help="emit stable metric JSON")

    structure_parser = subparsers.add_parser(
        "structure", help="build positioned words, OCR lines, tables, and cells"
    )
    structure_parser.add_argument("document_id", help="verified PageTrace document identifier")
    structure_parser.add_argument(
        "text_artifact_id", help="verified text-routing artifact identifier"
    )
    structure_parser.add_argument("ocr_artifact_id", help="verified routed-OCR artifact identifier")
    structure_parser.add_argument("--store", type=Path, default=Path(".pagetrace"))
    structure_parser.add_argument(
        "--json", action="store_true", help="emit the canonical structured artifact"
    )

    inspect_structure_parser = subparsers.add_parser(
        "inspect-structure", help="verify and inspect a stored structured artifact"
    )
    inspect_structure_parser.add_argument(
        "document_id", help="verified PageTrace document identifier"
    )
    inspect_structure_parser.add_argument(
        "artifact_id", help="canonical structured artifact identifier"
    )
    inspect_structure_parser.add_argument("--store", type=Path, default=Path(".pagetrace"))
    inspect_structure_parser.add_argument(
        "--json", action="store_true", help="emit the canonical structured artifact"
    )

    corpus_parser = subparsers.add_parser(
        "build-corpus", help="build deterministic page-bounded chunks with exact provenance"
    )
    corpus_parser.add_argument("document_id", help="verified PageTrace document identifier")
    corpus_parser.add_argument(
        "structure_artifact_id", help="verified structured artifact identifier"
    )
    corpus_parser.add_argument("--store", type=Path, default=Path(".pagetrace"))
    corpus_parser.add_argument(
        "--json", action="store_true", help="emit the canonical corpus artifact"
    )

    inspect_corpus_parser = subparsers.add_parser(
        "inspect-corpus", help="verify and inspect a stored corpus artifact"
    )
    inspect_corpus_parser.add_argument("document_id", help="verified PageTrace document identifier")
    inspect_corpus_parser.add_argument("artifact_id", help="canonical corpus artifact identifier")
    inspect_corpus_parser.add_argument("--store", type=Path, default=Path(".pagetrace"))
    inspect_corpus_parser.add_argument(
        "--json", action="store_true", help="emit the canonical corpus artifact"
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
        elif arguments.command == "inspect-text":
            artifact = load_text_extraction(
                arguments.artifact_id,
                document_id=arguments.document_id,
                store=arguments.store,
            )
            _print_text_extraction(artifact, as_json=arguments.json)
        elif arguments.command == "ocr":
            routing_policy = (
                OcrRoutingPolicy.CANDIDATES_ONLY
                if arguments.candidates_only
                else OcrRoutingPolicy.CANDIDATES_AND_SPARSE
            )
            ocr_artifact = ocr_document(
                arguments.document_id,
                arguments.text_artifact_id,
                store=arguments.store,
                configuration=OcrConfig(routing_policy=routing_policy),
            )
            _print_ocr_artifact(ocr_artifact, as_json=arguments.json)
        elif arguments.command == "inspect-ocr":
            ocr_artifact = load_ocr_artifact(
                arguments.artifact_id,
                document_id=arguments.document_id,
                store=arguments.store,
            )
            _print_ocr_artifact(ocr_artifact, as_json=arguments.json)
        elif arguments.command == "evaluate-ocr":
            evaluation = evaluate_ocr(
                _read_evaluation_text(arguments.reference),
                _read_evaluation_text(arguments.prediction),
            )
            _print_ocr_evaluation(evaluation, as_json=arguments.json)
        elif arguments.command == "structure":
            structured_artifact = structure_document(
                arguments.document_id,
                arguments.text_artifact_id,
                arguments.ocr_artifact_id,
                store=arguments.store,
            )
            _print_structured_document(structured_artifact, as_json=arguments.json)
        elif arguments.command == "inspect-structure":
            structured_artifact = load_structured_document(
                arguments.artifact_id,
                document_id=arguments.document_id,
                store=arguments.store,
            )
            _print_structured_document(structured_artifact, as_json=arguments.json)
        elif arguments.command == "build-corpus":
            corpus_artifact = build_corpus(
                arguments.document_id,
                arguments.structure_artifact_id,
                store=arguments.store,
            )
            _print_corpus_artifact(corpus_artifact, as_json=arguments.json)
        else:
            corpus_artifact = load_corpus_artifact(
                arguments.artifact_id,
                document_id=arguments.document_id,
                store=arguments.store,
            )
            _print_corpus_artifact(corpus_artifact, as_json=arguments.json)
    except (DocumentError, ExtractionError, OcrError, StructureError, CorpusError) as exc:
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


def _print_ocr_artifact(artifact: OcrArtifact, *, as_json: bool) -> None:
    if as_json:
        sys.stdout.buffer.write(serialize_ocr_artifact(artifact))
        return
    print(f"OCR artifact id: {artifact.artifact_id}")
    print(f"document id: {artifact.document_id}")
    print(f"source text artifact id: {artifact.source_text_artifact_id}")
    print(f"OCR engine: {artifact.processor.engine_name} {artifact.processor.engine_version}")
    print(
        f"inference backend: {artifact.processor.inference_backend_name} "
        f"{artifact.processor.inference_backend_version}"
    )
    print(f"selected pages: {artifact.selected_page_count}/{artifact.page_count}")
    for page in artifact.pages:
        print(
            f"page {page.page_number}: {page.status.value} "
            f"({page.non_whitespace_character_count} non-whitespace characters)"
        )


def _print_ocr_evaluation(evaluation: OcrEvaluation, *, as_json: bool) -> None:
    if as_json:
        sys.stdout.buffer.write(serialize_ocr_evaluation(evaluation))
        return
    print(f"exact match: {'yes' if evaluation.exact_match else 'no'}")
    print(
        f"character error rate: {evaluation.character_error_rate:.6f} "
        f"({evaluation.character_edits}/{evaluation.reference_character_count})"
    )
    print(
        f"word error rate: {evaluation.word_error_rate:.6f} "
        f"({evaluation.word_edits}/{evaluation.reference_word_count})"
    )


def _print_structured_document(artifact: StructuredDocumentArtifact, *, as_json: bool) -> None:
    if as_json:
        sys.stdout.buffer.write(serialize_structured_document(artifact))
        return
    print(f"structured artifact id: {artifact.artifact_id}")
    print(f"document id: {artifact.document_id}")
    print(f"source text artifact id: {artifact.source_text_artifact_id}")
    print(f"source OCR artifact id: {artifact.source_ocr_artifact_id}")
    print(f"pages: {artifact.page_count}")
    print(f"positioned text spans: {artifact.span_count}")
    print(f"tables: {artifact.table_count}")
    print(f"table cells: {artifact.cell_count}")
    for page in artifact.pages:
        print(
            f"page {page.page_number}: {len(page.spans)} spans, "
            f"{len(page.tables)} tables ({page.width:g} x {page.height:g} "
            f"{page.dimension_unit.value})"
        )


def _print_corpus_artifact(artifact: CorpusArtifact, *, as_json: bool) -> None:
    if as_json:
        sys.stdout.buffer.write(serialize_corpus_artifact(artifact))
        return
    print(f"corpus artifact id: {artifact.artifact_id}")
    print(f"document id: {artifact.document_id}")
    print(f"source structure artifact id: {artifact.source_structure_artifact_id}")
    print(f"processor: {artifact.processor.name} {artifact.processor.version}")
    print(f"pages: {artifact.page_count}")
    print(f"source text spans: {artifact.source_span_count}")
    print(f"source tables: {artifact.source_table_count}")
    print(f"chunks: {artifact.chunk_count}")
    print(f"chunk characters: {artifact.character_count}")
    for chunk in artifact.chunks:
        print(
            f"chunk {chunk.chunk_index}: page {chunk.page_number}, "
            f"{chunk.character_count} characters, {len(chunk.fragments)} fragments"
        )


def _read_evaluation_text(path: Path) -> str:
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise OcrEvaluationError("OCR evaluation input must be a regular non-symlink file")
        if metadata.st_size > _MAX_EVALUATION_TEXT_BYTES:
            raise OcrEvaluationError(
                f"OCR evaluation input exceeds {_MAX_EVALUATION_TEXT_BYTES} bytes"
            )
        data = path.read_bytes()
    except OcrEvaluationError:
        raise
    except OSError as exc:
        raise OcrEvaluationError("OCR evaluation input could not be read") from exc
    if len(data) != metadata.st_size:
        raise OcrEvaluationError("OCR evaluation input changed while it was read")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OcrEvaluationError("OCR evaluation input must be valid UTF-8") from exc
