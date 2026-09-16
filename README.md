# PageTrace

> Understand documents. Trace every answer to its source.

**PageTrace — Multimodal Document Intelligence Platform** is an early-stage project exploring how
document understanding systems can make evidence, provenance, and evaluation first-class concerns.

## Vision

PageTrace is guided by four ideas:

- **Traceability:** outputs should retain precise, inspectable links to source evidence.
- **Provenance:** transformations should record where information came from and how it changed.
- **Evaluation:** measurable quality should shape development from the first real capability.
- **Untrusted-document security:** document content is hostile data, never executable instruction.

## Current status

PageTrace is **pre-alpha**. Milestones 0, 1, and 2A are complete. Milestone 2B routed OCR and
evaluation is implemented on a development branch and pending acceptance. The current package can:

- stage untrusted local PDF, PNG, and JPEG files under explicit byte/page/pixel limits;
- identify supported media from content signatures and confirm it with pypdf or Pillow;
- compute full SHA-256 content fingerprints and deterministic document/page identities;
- persist canonical immutable manifests and the exact validated source bytes atomically; and
- verify manifest structure, identity, source size, and source fingerprint during readback;
- extract embedded PDF text with pypdf while preserving the returned text;
- reject extracted output above typed per-page and per-document character limits;
- route PDF pages with no usable embedded text and all PNG/JPEG pages as explicit OCR candidates;
- represent mixed digital/scanned-style PDFs with independent page-level states; and
- persist deterministic, versioned text artifacts separately from immutable ingestion manifests;
- render only OCR-candidate and policy-eligible sparse pages using PDFium;
- recognize routed page images with bundled RapidOCR PP-OCR models on CPU ONNX Runtime;
- persist immutable OCR artifacts linked to both document and text-routing provenance; and
- measure exact match, character error rate, and word error rate without hidden normalization.

An OCR-candidate status remains routing information rather than proof that OCR is necessary or
accurate. OCR output is untrusted derived data with measured confidence, not verified truth.
PageTrace does not analyze layout, extract tables, chunk or index content, perform retrieval/RAG,
use language/vision models, or answer questions.

## Planned conceptual pipeline

```text
untrusted documents
        |
secure deterministic ingestion (Milestone 1 complete)
        |
embedded PDF text + explicit OCR routing (Milestone 2A complete)
        |
real OCR engine and measured OCR evaluation (Milestone 2B pending acceptance)
        |
provenance-aware corpus construction (planned)
        |
retrieval and evidence evaluation (planned)
        |
evidence-grounded answers and product experiences (planned)
```

See [ROADMAP.md](ROADMAP.md) for milestone scope boundaries.

## Development setup

PageTrace requires Python 3.11 or later.

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,ocr]"
```

The base install remains sufficient for ingestion and Milestone 2A extraction. Install the `ocr`
extra only when running Milestone 2B OCR; it adds RapidOCR, CPU ONNX Runtime, and pypdfium2.

## Python API

```python
from pathlib import Path

from pagetrace.documents import ingest_document, load_document
from pagetrace.extraction import extract_document_text, load_text_extraction
from pagetrace.ocr import evaluate_ocr, load_ocr_artifact, ocr_document

manifest = ingest_document(Path("annual-report.pdf"), store=Path(".pagetrace"))
loaded = load_document(manifest.document_id, store=Path(".pagetrace"))
assert loaded == manifest

artifact = extract_document_text(manifest.document_id, store=Path(".pagetrace"))
loaded_artifact = load_text_extraction(
    artifact.artifact_id,
    document_id=manifest.document_id,
    store=Path(".pagetrace"),
)
assert loaded_artifact == artifact

ocr_artifact = ocr_document(
    manifest.document_id,
    artifact.artifact_id,
    store=Path(".pagetrace"),
)
assert (
    load_ocr_artifact(
        ocr_artifact.artifact_id,
        document_id=manifest.document_id,
        store=Path(".pagetrace"),
    )
    == ocr_artifact
)

evaluation = evaluate_ocr("expected text", ocr_artifact.pages[0].text or "")
print(evaluation.character_error_rate, evaluation.word_error_rate)
```

Expected document failures derive from `DocumentError`. More specific public errors distinguish
unsupported or malformed content, resource limits, encrypted PDFs, storage failures, and
persistence-integrity failures. `IngestionLimits` configures the Python API defaults:

| Limit | Default |
| --- | ---: |
| Maximum file size | 100 MiB |
| Maximum PDF pages | 2,000 |
| Maximum image pixels | 100,000,000 |

Limits can be changed deliberately for a deployment context:

```python
from pagetrace.documents import IngestionLimits, ingest_document

manifest = ingest_document(
    Path("small.png"),
    store=Path(".pagetrace"),
    limits=IngestionLimits(max_file_bytes=5 * 1024 * 1024),
)
```

Expected extraction failures derive from `ExtractionError`; source-document integrity failures
remain explicit `DocumentError` values. `ExtractionLimitError` distinguishes output-policy
rejection from parser, integrity, storage, and OCR-routing outcomes.

`TextExtractionConfig` captures the pypdf mode, routing threshold, and immutable
`ExtractionLimits` in artifact identity. Defaults bound accepted output to 2,000,000 characters per
page and 20,000,000 characters per document. Counts include every character returned by pypdf.
Limits are inclusive (`count <= limit` succeeds); PageTrace raises before accepting the page when a
count is greater, never truncates text, and never persists a partial artifact.
The 2-million/20-million defaults are intentionally far above ordinary digital page text while
placing a conservative pre-alpha ceiling on accepted page and artifact output.

```python
from pagetrace.extraction import ExtractionLimits, TextExtractionConfig

configuration = TextExtractionConfig(
    limits=ExtractionLimits(
        max_characters_per_page=250_000,
        max_characters_per_document=2_000_000,
    )
)
artifact = extract_document_text(
    manifest.document_id,
    store=Path(".pagetrace"),
    configuration=configuration,
)
```

With the default sufficiency threshold of four non-whitespace characters, zero becomes
`OCR_CANDIDATE`, one to three becomes `SPARSE_EMBEDDED_TEXT`, and four or more becomes
`EMBEDDED_TEXT`. This deterministic rule is not an OCR-quality classifier. Sparse means embedded
text exists below the configured sufficiency threshold; it does not mean the page is satisfactorily
resolved, and the page remains eligible for future Milestone 2B OCR policy/evaluation. Sparse and
embedded text is stored exactly as returned by pypdf. Whitespace-only output is not claimed as
extracted text.

By default, Milestone 2B selects both `OCR_CANDIDATE` and `SPARSE_EMBEDDED_TEXT` pages. A
candidates-only policy is available. PDFs render at 200 DPI; image documents use their verified
native pixels. Defaults allow at most 100 selected pages, 25 million pixels per page, 100 million
pixels per document, 1,000 detected lines per page, 2 million OCR characters per page, and 20
million OCR characters per document. Violations fail without truncation or partial persistence.

## CLI

```bash
pagetrace ingest annual-report.pdf --store .pagetrace
pagetrace inspect sha256-<64-lowercase-hex-characters> --store .pagetrace
pagetrace extract-text sha256-<64-lowercase-hex-characters> --store .pagetrace
pagetrace inspect-text sha256-<64-lowercase-hex-characters> \
  text-sha256-<64-lowercase-hex-characters> --store .pagetrace
pagetrace ocr sha256-<64-lowercase-hex-characters> \
  text-sha256-<64-lowercase-hex-characters> --store .pagetrace
pagetrace inspect-ocr sha256-<64-lowercase-hex-characters> \
  ocr-sha256-<64-lowercase-hex-characters> --store .pagetrace
pagetrace evaluate-ocr reference.txt prediction.txt --json

# The module entry point is equivalent.
python -m pagetrace ingest annual-report.pdf --store .pagetrace --json
```

Plain output reports document or artifact identity, provenance, page counts, and per-page routing.
`--json` emits the relevant canonical manifest, artifact, or metric object. Expected document,
extraction, OCR, and evaluation errors are concise, have a non-zero exit status, and do not display
a traceback.

## Artifact and identity design

Storage is content-addressed and never uses an input filename as a destination path:

```text
STORE/
|-- .staging/
`-- documents/
    `-- sha256-<full-digest>/
        |-- manifest.json
        |-- source.pdf | source.png | source.jpg
        `-- artifacts/
            |-- text/
            |   `-- text-sha256-<full-digest>.json
            `-- ocr/
                `-- ocr-sha256-<full-digest>.json
```

The canonical manifest uses schema version `1`, stable UTF-8 JSON serialization, a full SHA-256
fingerprint, and 1-based page numbering. Identical bytes produce identical document IDs, page IDs,
and manifests regardless of the input path or filename. Source filename, source path, timestamps,
temporary paths, usernames, and host information are deliberately excluded from the canonical
manifest.

Input is copied once into a same-store staging directory in bounded chunks while it is hashed.
Validation and final persistence use those staged bytes. A complete artifact is atomically moved
into its final directory, and re-ingestion verifies an existing artifact instead of overwriting it.

Text artifacts use their own schema version `1` and identity. The artifact ID is derived from the
document fingerprint, extraction schema, extractor/backend versions, and output-affecting
configuration, including extraction output limits—not from a filename, path, timestamp, machine,
username, or random UUID. Page
results retain the exact Milestone 1 page IDs. Canonical text-result bytes include an integrity
fingerprint; complete files are promoted atomically without overwriting contradictory artifacts.
Readback re-verifies both the text artifact and its underlying Milestone 1 source.

OCR artifacts use a separate schema-v1 identity derived from the document fingerprint, exact source
text-artifact identity and content fingerprint, routing/rendering/limit configuration, processor
version, installed RapidOCR/ONNX Runtime/PDFium versions, and SHA-256 of the three bundled model
files. Page results record source routing status, whether OCR ran, rendered dimensions, exact OCR
text, bounded counts, and rounded mean line confidence. Readback re-verifies every provenance link.

## Security boundary and limits

Milestone 1 rejects missing paths, directories, symbolic-link inputs, empty/unsupported/malformed
files, encrypted PDFs, excessive file/page/pixel counts, and multi-frame images. Pillow
decompression-bomb conditions become explicit document-limit errors. Readback rejects unsafe IDs,
unknown schema versions, malformed manifests, missing/unsafe files, and source size/fingerprint
mismatches.

Character limits bound text accepted into each page result and the cumulative canonical artifact;
they are checked only after `pypdf.extract_text` returns. They do not sandbox pypdf or prevent a
malicious compressed/content stream from consuming parser CPU or RAM first. pypdf and Pillow remain
in-process, and OS/subprocess memory and time isolation does not exist. Parser vulnerabilities and
filesystem, race, or deeply nested PDF denial-of-service scenarios remain possible. See
[SECURITY.md](SECURITY.md) for the precise implemented controls and residual risks.

OCR page/pixel limits are checked before rendering; actual dimensions are checked again after
rendering, and line/text limits are checked after RapidOCR returns. RapidOCR, ONNX Runtime,
PDFium, and image codecs still run in-process without hard CPU, memory, or wall-clock isolation.
The bundled models avoid runtime model downloads, but optional dependency installation remains a
supply-chain operation.

All extracted text remains untrusted document data. PageTrace does not execute embedded commands,
scripts, URLs, or instruction-like text, and no extracted content should be treated as a system or
model instruction.

## Quality and validation

```bash
ruff check .
ruff format --check .
mypy src tests
pytest
python -m build
python -m twine check --strict dist/*
git diff --check
```

`pytest` enforces branch-aware coverage with a 90% minimum. The contribution guide documents the
clean-wheel import and CLI smoke tests used by continuous integration.

## Project policies

- [CONTRIBUTING.md](CONTRIBUTING.md) — local workflow and quality expectations
- [SECURITY.md](SECURITY.md) — implemented controls, residual risks, and reporting
- [ROADMAP.md](ROADMAP.md) — milestone responsibilities
- [CHANGELOG.md](CHANGELOG.md) — unreleased changes

## License

PageTrace is available under the [MIT License](LICENSE).
