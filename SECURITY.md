# Security Policy

PageTrace is designed for documents that may be malformed, adversarial, sensitive, or simply
unexpected. Milestone 1 implements the accepted bounded local ingestion boundary for PDF, PNG, and
JPEG. Milestone 2A adds in-process embedded PDF text extraction and explicit OCR-candidate routing
on `feat/milestone-2a-text-extraction`. Neither stage provides complete document sandboxing.

## Implemented Milestone 1 protections

- Input must exist, be non-empty, be a regular file, and not be a symbolic link.
- Source bytes are copied once into a system-named, same-store staging directory in bounded chunks;
  SHA-256 is computed during that copy, and the exact staged bytes are validated and persisted.
- File size (100 MiB), PDF page count (2,000), and image pixel count (100 million) have typed,
  configurable defaults and are enforced with domain errors.
- PDF/PNG/JPEG type detection uses content signatures and is confirmed by strict pypdf or Pillow
  parsing; plausible signatures alone are insufficient.
- Encrypted PDFs and multi-frame images are rejected. PageTrace does not accept passwords or
  attempt active-content, attachment, URL, macro, or script execution.
- Pillow decompression-bomb warnings/errors and the configured pixel ceiling are enforced.
- Full SHA-256 values produce path-safe document identities. Storage source names come only from
  detected media types, never untrusted filenames.
- Frozen typed manifests use schema version `1`, deterministic UTF-8 JSON, an immutable page tuple,
  and content-derived values only.
- Completed artifacts are promoted atomically. Existing content-addressed artifacts are verified,
  never silently overwritten or repaired.
- Readback validates IDs, schema and field structure, page consistency, source existence/safety,
  byte size, and the complete stored-source fingerprint.
- Temporary ingestion directories are removed after successful and failed validation.

Targeted tests cover byte/page/pixel limits, malformed files, encrypted PDFs, unsafe IDs, manifest
corruption, stored-source tampering, deterministic re-ingestion, and cleanup. Symlink tests skip
only on platforms or accounts that do not permit creating the test link; production rejection is
unconditional.

## Implemented Milestone 2A protections

- Extraction accepts only a canonical document ID already persisted and verified by Milestone 1;
  there is no arbitrary-file extraction bypass.
- The source is fingerprint-verified before processing. PDF bytes are opened without following a
  symbolic link where the platform supports it, rehashed from the opened handle, and compared with
  the immutable document manifest before pypdf receives them.
- Page results retain the exact Milestone 1 document fingerprint, document ID, page IDs, and
  contiguous page numbers.
- Embedded text is preserved as returned by pypdf. Status is stored separately from text, and
  OCR-candidate pages never contain placeholder or fabricated OCR output.
- Typed output limits accept at most 2,000,000 extracted characters per page and 20,000,000 per
  document by default. Limits are inclusive, configurable through the Python API, enforced after
  every page extraction, and violations fail before artifact persistence without truncation.
- The deterministic routing threshold, extraction mode, and both output limits are captured in
  configuration and artifact identity. The extractor-stage version and actual installed pypdf
  version also participate.
- Frozen schema-v1 text artifacts use canonical UTF-8 JSON and a canonical page-content checksum.
  Unsafe artifact IDs, unknown schemas, malformed values, inconsistent status/text, and identity,
  page, fingerprint, or content contradictions are rejected.
- Text artifacts are stored under system-derived paths separate from the immutable source and
  ingestion manifest. Complete temporary files are flushed and promoted without overwriting an
  existing artifact; failed promotions clean up temporary files.
- Every text-artifact read re-verifies the underlying Milestone 1 source. Source tampering therefore
  invalidates both new extraction and existing extraction-artifact readback.

Text extracted from a document remains untrusted data. PageTrace does not execute embedded
commands, URLs, scripts, model instructions, or prompt-injection text. Milestone 2A does not pass
document text to a shell, browser, model, service, or other execution environment.

## Security principles

- Treat every document and all extracted content as untrusted data.
- Never treat document text as executable instructions, even when it resembles system, developer,
  tool, or user directions.
- Apply least privilege, explicit resource limits, deterministic processing, and auditable
  transformations as functionality is introduced.
- Minimize retention and external disclosure of sensitive documents.
- Make security properties measurable and test regressions as early as related behavior exists.

## Residual risks and future security work

Milestones 1 and 2A are in-process parser boundaries, not operating-system sandboxes. Residual risks
include vulnerabilities or pathological CPU/memory behavior in pypdf text/content-stream parsing,
Pillow, Python, or native image codecs; very large decompressed text streams; deeply nested PDF
object graphs; filesystem exhaustion; storage-root tampering by a separate privileged process; and
source/storage mutation races. Existing byte/page/pixel bounds and repeated fingerprint checks
reduce exposure but cannot solve every denial-of-service or local-adversary scenario. Extraction
character limits bound accepted page output and cumulative canonical artifact size only after
`extract_text` returns. Malicious compressed/content streams may consume pypdf CPU or RAM before
that check. Milestone 2A does not claim CPU, memory, time, subprocess, or parser isolation.

Future threat modeling and milestones will cover at least:

- malformed files and parser vulnerabilities;
- resource exhaustion beyond the current byte/page/pixel ceilings;
- unexpected embedded files, scripts, links, and active content;
- malicious or misleading document text;
- prompt injection against future model-assisted processing;
- confidential, regulated, or personally identifiable content; and
- unintended exposure to future external model or service providers.

Prompt injection is already a data-handling concern because Milestone 2A extracts untrusted text,
but no model or external service consumes that text yet. Model-provider disclosure, process
isolation, broader quotas, privacy controls, supply-chain hardening, and operational incident
controls remain later roadmap responsibilities.

## Supported versions

PageTrace has no public release yet. Security fixes currently target the active development branch.
A supported-version table will be added when releases begin.

## Reporting a vulnerability

Avoid public issues for vulnerabilities or sensitive reproduction material. If the repository host
offers GitHub private vulnerability reporting or a private security advisory, prefer that channel;
this policy does not claim that the feature is enabled. If no private channel is available, contact
the maintainers privately through the hosting platform before sharing details.

Include the affected revision, impact, minimal reproduction steps, and any suggested mitigation.
Do not include real sensitive documents unless a secure transfer method has been agreed upon.
