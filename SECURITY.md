# Security Policy

PageTrace is designed for documents that may be malformed, adversarial, sensitive, or simply
unexpected. Milestone 1 implements a bounded local ingestion boundary for PDF, PNG, and JPEG on the
`feat/milestone-1-ingestion` branch. It does **not** provide complete document sandboxing.

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

## Security principles

- Treat every document and all future extracted content as untrusted data.
- Never treat document text as executable instructions, even when it resembles system, developer,
  tool, or user directions.
- Apply least privilege, explicit resource limits, deterministic processing, and auditable
  transformations as functionality is introduced.
- Minimize retention and external disclosure of sensitive documents.
- Make security properties measurable and test regressions as early as related behavior exists.

## Residual risks and future security work

Milestone 1 is an in-process parser boundary, not an operating-system sandbox. Residual risks
include vulnerabilities or pathological CPU/memory behavior in pypdf, Pillow, Python, or native
image codecs; deeply nested PDF object graphs; filesystem exhaustion; storage-root tampering by a
separate privileged process; and source mutation races that preserve observable file attributes.
The bounded staging design detects common mutation and limits byte retention, but cannot solve all
denial-of-service or local adversary scenarios.

Future threat modeling and milestones will cover at least:

- malformed files and parser vulnerabilities;
- resource exhaustion beyond the current byte/page/pixel ceilings;
- unexpected embedded files, scripts, links, and active content;
- malicious or misleading document text;
- prompt injection against future model-assisted processing;
- confidential, regulated, or personally identifiable content; and
- unintended exposure to future external model or service providers.

Prompt injection and model-provider disclosure are future concerns because Milestone 1 does not
extract document text or call models/services. Process isolation, broader quotas, privacy controls,
supply-chain hardening, and operational incident controls remain later roadmap responsibilities.

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
