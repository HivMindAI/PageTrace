# Changelog

All notable changes to PageTrace will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
intends to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) when releases begin.

## [Unreleased]

### Added

- Initial `src/`-layout Python package with a PEP 561 typing marker.
- Standards-based Hatchling packaging metadata for development version `0.1.0.dev0`.
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
