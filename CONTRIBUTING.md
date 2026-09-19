# Contributing to PageTrace

PageTrace is currently pre-alpha. Contributions should keep each milestone small, testable, and
truthful about what exists.

## Supported Python versions

Development supports Python 3.11 and 3.12. The package metadata allows Python 3.11 or later; new
language features must remain compatible with Python 3.11.

## Local setup

Create an isolated environment and install the project plus its development tools:

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,ocr,structure]"

# Frontend toolchain (Node.js 22 or newer)
cd web
npm ci
cd ..
```

The editable installation is required so tests import the installed `src/` package rather than
depending on the repository root being importable.

## Required checks

Run these commands before requesting review:

```bash
ruff check .
ruff format --check .
mypy src tests
pytest
python -m build
python -m twine check --strict dist/*
git diff --check
cd web
npm run lint
npm test
npm run build
cd ..
git diff --exit-code -- src/pagetrace/web/dist
```

Use `ruff format .` to apply formatting. Do not weaken lint, typing, test, or coverage gates merely
to make continuous integration pass; fix the underlying issue or document a narrowly justified
exception.

`pytest` includes branch coverage and fails below 90%. Behavior changes must include focused tests
that demonstrate the intended result and meaningful failure cases.

Frontend changes must keep the TypeScript client strict, render backend/document values as text,
avoid persistent token storage, and commit the production build under `src/pagetrace/web/dist` so
the Python wheel remains directly runnable. `npm run build` must leave those packaged assets clean.

## Clean-wheel smoke test

After `python -m build`, create a fresh virtual environment, install the wheel from `dist/`, move
outside the source checkout, and run:

```bash
python -m pip install dist/*.whl
python -I -c "import pagetrace; print(pagetrace.__name__)"
pagetrace --help
pagetrace extract-text --help
pagetrace ocr --help
pagetrace inspect-ocr --help
pagetrace evaluate-ocr --help
pagetrace structure --help
pagetrace inspect-structure --help
pagetrace-backend --help
python -I -m pagetrace --help
python -I -m pagetrace extract-text --help
python -I -m pagetrace ocr --help
python -I -m pagetrace structure --help
```

The smoke test must use the wheel's interpreter and must not rely on an editable installation,
`PYTHONPATH`, or the source checkout. Installing the wheel must resolve its declared pypdf and
Pillow runtime dependencies. The GitHub Actions workflow provides the canonical automated
implementation of this check.

## Document-ingestion changes

Document fixtures should be tiny and generated programmatically where practical. Tests involving
untrusted documents must exercise real parser/storage behavior and relevant failure cases rather
than mocking away the ingestion boundary. Preserve deterministic manifests: do not add source
paths, filenames, timestamps, machine identity, or other environment-derived values to the
canonical artifact.

Milestone 1 runtime dependencies are intentionally limited to pypdf (BSD-3-Clause) for PDF
structure inspection and Pillow (MIT-CMU) for PNG/JPEG validation and metadata. New runtime
dependencies require a documented capability need and license review.

## Text-extraction changes

Extraction must begin from a stored document that passes Milestone 1 readback. Do not add a direct
arbitrary-file extraction path or mutate the canonical ingestion manifest/source. Text artifacts
are separate derived values with deterministic identity, immutable page results, explicit
extractor/configuration provenance, atomic persistence, and verified readback.

Use real tiny generated PDFs for primary embedded-text and mixed-page behavior. Narrow mocks are
appropriate only for parser/storage failure boundaries. Preserve pypdf output faithfully; do not
normalize case, punctuation, whitespace, accents, or language direction. An OCR-candidate status
must have no invented text. Milestone 2A intentionally has no OCR engine, model download, PDF page
renderer, image preprocessing, layout analysis, retrieval, RAG, or model integration.

Every extraction configuration must retain positive typed per-page and per-document character
limits. Defaults are 2,000,000 and 20,000,000 respectively, with inclusive acceptance. Enforce
limits page-by-page before accepting results; never truncate, convert a violation into an OCR
candidate, or persist a partial artifact. Limits belong in deterministic provenance and artifact
identity. Tests should use deliberately small values for boundary and cumulative behavior.

`SPARSE_EMBEDDED_TEXT` means pypdf returned text below the configured sufficiency threshold. It is
not a resolved-quality claim and remains eligible for future OCR routing/evaluation policy.
Character limits bound accepted output after pypdf returns; they do not sandbox its CPU or memory
use. pypdf remains in-process without subprocess, time, or memory isolation.

pypdf is reused for embedded text, so Milestone 2A adds no runtime dependency. OCR dependencies are
isolated in the optional `ocr` extra and require separate capability, security, license, size, and
evaluation review when changed.

## OCR and evaluation changes

OCR must start from a verified Milestone 2A text artifact and render only pages selected by the
captured routing policy. Keep RapidOCR, ONNX Runtime, and pypdfium2 behind the optional `ocr` extra;
the base wheel and CLI help must remain importable without them. Do not download models at runtime.
The selected profile uses model files bundled in the RapidOCR wheel and fingerprints their bytes.

Preserve exact OCR output; do not silently normalize, correct, translate, or fabricate text. Enforce
page, pixel, line, and character limits without truncation or partial artifact persistence. Engine,
inference, renderer, model-byte, source-routing, configuration, and document provenance must remain
part of the immutable artifact contract. Accuracy tests must use declared reference text and report
transparent exact/CER/WER measurements without claiming general language or document quality.

## Structured-representation changes

Structure construction must begin from one verified document, its exact Milestone 2A text artifact,
and a Milestone 2B OCR artifact derived from that text artifact. Keep pdfplumber behind the optional
`structure` extra and retain lazy imports so the base wheel and CLI help work without it. OCR
geometry replay must use the exact recorded OCR processor and configuration; do not accept geometry
when replayed text, line count, or mean confidence changes.

All page, word, OCR-line, table, and cell coordinates use an explicit top-left origin. PDF units are
points and image units are pixels. Validate finite positive-area boxes against page/table bounds,
retain exact prior-stage provenance, enforce typed span/table/cell limits without truncation, and
never persist a partial artifact. Real generated vector-table PDFs should exercise the pdfplumber
boundary; narrow mocks remain appropriate for malformed-output and limit failures.

pdfplumber is an MIT-licensed optional dependency. Changes to its version range or replacement
still require capability, security, compatibility, and license review.

## Git hygiene

- Keep changes scoped to one coherent concern.
- Review `git status` and `git diff` before sharing work.
- Do not commit virtual environments, caches, coverage data, build products, or secrets.
- Write clear commit messages and avoid unrelated formatting churn.
- Update documentation and the `[Unreleased]` changelog when behavior or contributor workflow
  changes.
- Do not bypass branch protections or publish packages from a development branch.
