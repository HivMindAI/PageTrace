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

PageTrace is **pre-alpha**. Milestone 1 secure deterministic ingestion is implemented on the
`feat/milestone-1-ingestion` branch and is pending architectural acceptance. The current package
can:

- stage untrusted local PDF, PNG, and JPEG files under explicit byte/page/pixel limits;
- identify supported media from content signatures and confirm it with pypdf or Pillow;
- compute full SHA-256 content fingerprints and deterministic document/page identities;
- persist canonical immutable manifests and the exact validated source bytes atomically; and
- verify manifest structure, identity, source size, and source fingerprint during readback.

It does **not** extract text, run OCR, render PDF pages, analyze layout, index content, perform
retrieval, use language/vision models, or answer questions.

## Planned conceptual pipeline

```text
untrusted documents
        |
secure deterministic ingestion (Milestone 1 implemented, pending acceptance)
        |
text and structure extraction (planned)
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
python -m pip install -e ".[dev]"
```

## Python API

```python
from pathlib import Path

from pagetrace.documents import ingest_document, load_document

manifest = ingest_document(Path("annual-report.pdf"), store=Path(".pagetrace"))
loaded = load_document(manifest.document_id, store=Path(".pagetrace"))
assert loaded == manifest
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

## CLI

```bash
pagetrace ingest annual-report.pdf --store .pagetrace
pagetrace inspect sha256-<64-lowercase-hex-characters> --store .pagetrace

# The module entry point is equivalent.
python -m pagetrace ingest annual-report.pdf --store .pagetrace --json
```

Plain output reports the document ID, SHA-256 fingerprint, media type, and page count. `--json`
emits the canonical manifest. Expected document errors are concise, have a non-zero exit status,
and do not display a traceback.

## Artifact and identity design

Storage is content-addressed and never uses an input filename as a destination path:

```text
STORE/
|-- .staging/
`-- documents/
    `-- sha256-<full-digest>/
        |-- manifest.json
        `-- source.pdf | source.png | source.jpg
```

The canonical manifest uses schema version `1`, stable UTF-8 JSON serialization, a full SHA-256
fingerprint, and 1-based page numbering. Identical bytes produce identical document IDs, page IDs,
and manifests regardless of the input path or filename. Source filename, source path, timestamps,
temporary paths, usernames, and host information are deliberately excluded from the canonical
manifest.

Input is copied once into a same-store staging directory in bounded chunks while it is hashed.
Validation and final persistence use those staged bytes. A complete artifact is atomically moved
into its final directory, and re-ingestion verifies an existing artifact instead of overwriting it.

## Security boundary and limits

Milestone 1 rejects missing paths, directories, symbolic-link inputs, empty/unsupported/malformed
files, encrypted PDFs, excessive file/page/pixel counts, and multi-frame images. Pillow
decompression-bomb conditions become explicit document-limit errors. Readback rejects unsafe IDs,
unknown schema versions, malformed manifests, missing/unsafe files, and source size/fingerprint
mismatches.

This is not a process sandbox. pypdf and Pillow still parse untrusted bytes in the PageTrace
process, parser vulnerabilities remain possible, and resource limits cannot eliminate every CPU,
memory, filesystem, race, or deeply nested PDF denial-of-service scenario. See
[SECURITY.md](SECURITY.md) for the precise implemented controls and residual risks.

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
