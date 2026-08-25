# Security Policy

PageTrace is being designed for documents that may be malformed, adversarial, sensitive, or simply
unexpected. Milestone 0 establishes project policy and quality controls only; it does **not**
implement document sandboxing, ingestion validation, or other runtime security boundaries.

## Security principles

- Treat every document and all extracted content as untrusted data.
- Never treat document text as executable instructions, even when it resembles system, developer,
  tool, or user directions.
- Apply least privilege, explicit resource limits, deterministic processing, and auditable
  transformations as functionality is introduced.
- Minimize retention and external disclosure of sensitive documents.
- Make security properties measurable and test regressions as early as their related behavior
  exists.

Future threat modeling will cover at least:

- malformed files and parser vulnerabilities;
- resource exhaustion and decompression or page-count abuse;
- unsafe paths, filename handling, and path traversal;
- unexpected embedded files, scripts, links, and active content;
- malicious or misleading document text;
- prompt injection against model-assisted processing;
- confidential, regulated, or personally identifiable document content;
- unintended exposure to external model or service providers.

These risks are roadmap responsibilities, not protections claimed by the current package.

## Supported versions

PageTrace has no public release yet. Security fixes currently target the active development branch.
A supported-version table will be added when releases begin.

## Reporting a vulnerability

Please avoid public issues for vulnerabilities or sensitive reproduction material. If the
repository host offers GitHub private vulnerability reporting or a private security advisory,
prefer that channel; this policy does not claim that the feature is enabled. If no private channel
is available, contact the repository maintainers privately through the hosting platform before
sharing details.

Include the affected revision, impact, minimal reproduction steps, and any suggested mitigation.
Do not include real sensitive documents unless a secure transfer method has been agreed upon.

