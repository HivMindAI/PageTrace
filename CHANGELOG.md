# Changelog

All notable changes to PageTrace will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
intends to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) when releases begin.

## [Unreleased]

## [1.0.1] - 2026-09-19

### Changed

- Upgraded the frontend verification toolchain to Vite 8.3 and Vitest 5.0.1 after the `v1.0.0`
  candidate was blocked by newly reported npm audit findings in their older dependency chains.
- Synchronized Python and web package metadata at version 1.0.1. This patch changes release
  tooling dependencies and metadata without expanding PageTrace's accepted functional scope.

## [1.0.0] - 2026-09-19

### Added

- A formal acceptance record mapping Milestones 2B through 11 to their implementation commits,
  validation evidence, and retained scope boundaries.
- Milestone 11 atomic `portfolio-demo` workflow with a deterministic two-page PDF, complete
  document-to-evidence processing, exact cited answer, explicit no-hit abstention, canonical
  retrieval/quality outputs, file digests, and machine-readable claim limitations.
- A constrained v1.0 reference environment, reproduction/portfolio/release guides, synchronized
  package and web metadata, and a tag-only workflow that audits and verifies the project,
  reproduces evidence twice, builds distributions, and uploads a checksummed review bundle.
- Milestone 10 backend hardening with exact loopback Host/Origin validation, duplicate-authority
  rejection, bounded stalled-connection handling, stronger same-origin response headers, and
  adversarial HTTP tests.
- A configurable 10,000-job retained-record ceiling plus a bounded oldest-first terminal-job purge
  that previews by default, requires explicit confirmation, preserves active jobs, and cascades
  lifecycle-event deletion, with SQLite secure deletion requested as defense in depth.
- Weekly Dependabot coverage for Python, npm, and GitHub Actions, CI audits for Python runtime and
  frontend build dependencies, immutable CI action pins, and deployment/incident-response runbooks
  covering least privilege, retention, backup/restore, monitoring, containment, evidence
  preservation, and recovery.
- Milestone 9 responsive TypeScript Evidence Desk for document intake, evidence-grounded questions,
  quality evaluation, durable job/event inspection, cancellation, known-job reopening, and
  operational counters.
- Evidence-focused result views for document/page identity, exact citation slices, retrieval ranks,
  source coordinates, lexical coverage and abstention, quality metrics, gates, regressions, and
  findings, with memory-only bearer authentication and safe text rendering.
- Packaged same-origin frontend delivery with strict static path/symlink checks, bounded assets,
  CSP, anti-framing, MIME-sniffing/referrer/permissions controls, immutable fingerprinted assets,
  frontend lint/tests/build, and clean-wheel asset verification.
- Milestone 8 standard-library product backend with a durable SQLite job queue, canonical request
  fingerprints, idempotent submission, bounded retries/results/events, cancellation, interrupted-job
  recovery, and append-only lifecycle history.
- Injected deterministic workflow handlers for ingestion, evidence-grounded QA, and quality
  evaluation; authenticated loopback JSON endpoints for jobs, events, metrics, health, and
  readiness; and a `pagetrace-backend` operator CLI with separate initialization, worker, and
  serving modes.
- Milestone 7 canonical cross-stage quality suites and reports consolidating text-error, retrieval,
  answer, provenance, safety, structured human-review, and deterministic resource metrics.
- Explicit metric gates, minimum sample floors, directional baseline-regression rules, stable
  findings, strict integrity-checked JSON, Python APIs, and an `evaluate-quality` CLI command with
  distinct passed/failed/incomplete exit behavior and clean-wheel coverage.
- Milestone 6 deterministic extractive QA whose answer text is restricted to exact retrieved
  character slices, with stable evidence selection, embedded retrieval provenance, strict
  citation/offset verification, and canonical schema-v1 result identity and checksums.
- Explicit no-hit, insufficient-coverage, and answer-limit abstention; typed evidence/answer bounds;
  Python APIs; an `answer` CLI command; security documentation; tests; and clean-wheel smoke
  coverage without language-model or external-service dependencies.
- Milestone 5 deterministic Unicode-tokenized Okapi BM25 retrieval with stable ranking, exact
  corpus/chunk/page/region provenance, query limits, canonical result identities, and checksums.
- Canonical binary relevance datasets plus Precision@k, Recall@k, MRR, MAP, and nDCG evaluation,
  Python APIs, `retrieve`/`evaluate-retrieval` CLI commands, tests, and clean-wheel smoke coverage.
- Milestone 4 immutable schema-v1 corpus artifacts with deterministic page-bounded chunks, stable
  chunk identities, exact source-span/chunk character offsets, positioned evidence regions, and
  complete structured-artifact lineage.
- Deterministic oversized-span splitting, explicit separator policy, typed chunk/fragment/character
  limits, canonical JSON and checksums, atomic persistence, source reconstruction on readback, Python
  APIs, `build-corpus`/`inspect-corpus` CLI commands, and clean-wheel smoke coverage.
- Milestone 3 immutable schema-v1 structured-document artifacts with positioned embedded PDF words,
  replay-verified OCR lines, explicit top-left PDF-point/image-pixel coordinates, and exact
  document/text/OCR provenance.
- Deterministic pdfplumber line-based PDF table detection with positioned cells, stable ordering,
  typed span/table/cell limits, canonical JSON, content checksums, atomic storage, and strict
  provenance-verified readback.
- Structured-document Python APIs plus `pagetrace structure` and `pagetrace inspect-structure`
  commands, optional `structure` dependencies, real vector-table integration coverage, and
  clean-wheel CLI smoke checks.
- Routed Milestone 2B OCR for verified `OCR_CANDIDATE` and policy-eligible sparse pages using
  RapidOCR with bundled PP-OCR models, CPU ONNX Runtime, and PDFium rendering for selected PDF pages.
- Immutable schema-v1 OCR artifacts with document/text-routing provenance, engine/backend/renderer
  versions, bundled-model fingerprints, deterministic identity, canonical JSON, atomic storage,
  content checksums, and integrity-checked readback.
- Typed OCR page/pixel/line/character limits, candidates-only routing option, CLI/Python APIs, and
  exact-match/CER/WER evaluation without hidden text normalization.
- Initial `src/`-layout Python package with a PEP 561 typing marker.
- Standards-based Hatchling packaging metadata for version `1.0.0`.
- Ruff, strict mypy, pytest, branch coverage, build, and distribution validation configuration.
- GitHub Actions checks for Python 3.11 and 3.12 plus clean-wheel import validation.
- Project, contribution, security, roadmap, licensing, and repository support documentation.
- Secure deterministic PDF, PNG, and JPEG ingestion with content-based detection and parser
  validation.
- Configurable byte, PDF-page, and image-pixel limits plus explicit malformed, encrypted, and
  unsupported document errors.
- Full SHA-256 document fingerprints, deterministic document/page identities, immutable schema-v1
  manifests, and stable UTF-8 JSON serialization.
- Same-filesystem bounded staging, atomic content-addressed local persistence, idempotent
  re-ingestion, and verified readback that detects manifest/source corruption.
- Typed Python ingestion/readback API and standard-library `pagetrace ingest` / `pagetrace inspect`
  CLI with an equivalent `python -m pagetrace` entry point.
- pypdf and Pillow as the only runtime dependencies required for supported-format validation.
- Behavioral and security tests covering limits, traversal, malformed/encrypted content,
  deterministic identity, persistence integrity, cleanup, and CLI behavior.
- Deterministic pypdf embedded-text extraction for verified stored PDFs with faithful text
  preservation and page-level embedded, sparse, and OCR-candidate routing.
- Explicit PNG/JPEG OCR-candidate artifacts that contain no fabricated OCR text and do not re-encode
  or preprocess the validated image.
- Immutable schema-v1 text extraction artifacts with document/page fingerprint linkage, real pypdf
  version provenance, configuration-derived identities, canonical UTF-8 JSON, and content checksums.
- Typed, configurable extraction output limits with inclusive defaults of 2,000,000 characters per
  page and 20,000,000 per document, deterministic provenance, explicit limit errors, and no partial
  artifact or silent truncation on rejection.
- Separate atomic text-artifact persistence, idempotent repeated extraction, contradiction
  detection, and readback that re-verifies the underlying Milestone 1 source.
- Typed extraction/readback Python APIs plus `pagetrace extract-text` and
  `pagetrace inspect-text` commands with human-readable and canonical JSON output.
- Behavioral, mixed-PDF, determinism, provenance, corruption, cleanup, source-tampering, strict
  schema, and CLI tests for the Milestone 2A boundary.
