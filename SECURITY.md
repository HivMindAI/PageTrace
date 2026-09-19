# Security Policy

PageTrace is designed for documents that may be malformed, adversarial, sensitive, or simply
unexpected. Milestone 1 implements the accepted bounded local ingestion boundary for PDF, PNG, and
JPEG. Milestone 2A adds in-process embedded PDF text extraction and explicit OCR-candidate routing.
Milestone 2B adds bounded, routed PDFium rendering and RapidOCR inference. Milestone 3 adds
pdfplumber layout/table parsing and deterministic OCR geometry replay. Milestone 4 adds bounded
deterministic chunk construction and full structure-to-corpus reconstruction checks without
introducing another parser or model. Milestone 5 adds bounded in-process lexical BM25 retrieval and
binary relevance evaluation. Milestone 6 adds local deterministic extractive QA with structural
evidence enforcement and explicit abstention. Milestone 7 adds bounded local aggregation of
validated evaluation objects, structured human rubrics, quality gates, and regression checks.
Milestone 8 adds a bounded durable local job queue and authenticated loopback HTTP boundary.
Milestone 9 adds a packaged same-origin evidence inspection interface. Milestone 10 adds HTTP
authority/timeout hardening, retained-data quotas and bounded deletion, dependency
maintenance/auditing, and deployment/incident runbooks. Milestone 11 adds a synthetic,
digest-indexed portfolio demonstration and a constrained tag-build process without processing or
publishing private user documents. None of these stages provides complete document sandboxing or a
hardened multi-tenant service.

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

## Implemented Milestone 2B protections

- OCR requires an existing verified text-routing artifact and selects only `OCR_CANDIDATE` pages
  plus policy-eligible `SPARSE_EMBEDDED_TEXT` pages. Embedded-text pages are not rendered.
- PDF pages are preflighted at a fixed captured DPI against per-page and cumulative pixel limits;
  actual rendered dimensions are checked again. Verified images use their original bounded pixels.
- OCR defaults cap selected pages, rendered pixels, detected lines, and accepted characters.
  Violations raise before persistence and never truncate output or produce a partial artifact.
- RapidOCR uses CPU ONNX Runtime with single-thread inference settings and fixed bundled PP-OCR
  model paths. PageTrace does not invoke RapidOCR's model downloader.
- OCR provenance records processor, engine, inference backend, optional PDF renderer, fixed model
  profile, the combined SHA-256 of model bytes, routing policy, confidence threshold, rendering
  settings, limits, and the exact source text artifact.
- Canonical schema-v1 OCR artifacts use separate system-derived paths, atomic no-overwrite
  promotion, page-content checksums, strict readback, and document/text-artifact re-verification.
- Evaluation compares caller-provided UTF-8 strings exactly and reports exact match, character
  error rate, and word error rate without hidden normalization or an accuracy claim.

## Implemented Milestone 3 protections

- Structure construction requires one verified document, text-routing artifact, and OCR artifact;
  the OCR artifact must derive from the selected text artifact.
- PDF words, tables, and cells use finite, bounded top-left coordinates checked against verified
  display dimensions. Image/OCR coordinates use verified pixel dimensions.
- OCR geometry is accepted only after replaying the exact recorded processor/configuration and
  matching the stored page text, line count, and rounded mean confidence.
- Typed limits cap spans per page/document, tables per page/document, and cells per table/document.
  Violations fail before persistence without truncation or partial artifacts.
- Canonical schema-v1 structure artifacts include exact prior-stage content fingerprints,
  processor/backend versions, configuration, content checksums, atomic no-overwrite persistence,
  strict readback, and full provenance re-verification.

Line-based table detection and OCR geometry remain untrusted derived data. Coordinates establish
traceable regions, not semantic correctness or reading-order accuracy.

## Implemented Milestone 4 protections

- Corpus construction accepts only an existing structured artifact whose complete earlier-stage
  provenance is successfully reverified.
- Chunks never cross page boundaries. Every fragment records exact source-span and chunk character
  offsets, bounding region, coordinate unit/origin, evidence source, and stable ordering.
- Oversized spans are split deterministically into gap-free slices; text is never silently dropped
  or truncated. Empty structured pages produce no fabricated chunk.
- Typed limits cap chunks per page/document, fragments per chunk/document, and cumulative chunk
  characters. Violations fail before persistence without a partial artifact.
- Schema-v1 corpus artifacts record the source structure identity/content fingerprint, processor
  version, output-affecting configuration, limits, per-chunk checksums, and a corpus checksum.
- Atomic no-overwrite persistence uses system-derived paths. Every readback reloads the structured
  source and regenerates the expected artifact, rejecting any lineage, text, offset, region, order,
  identity, or configuration contradiction.

Chunking does not make source text trustworthy or semantically correct. Tables remain available
through the linked structured artifact and are not duplicated into speculative table text.

## Implemented Milestone 5 protections

- Retrieval accepts only a corpus artifact whose complete document-to-corpus provenance is
  successfully reverified during loading.
- The tokenizer and BM25 implementation are local, deterministic, versioned, and dependency-free.
  Processor identity records the tokenizer version and Python Unicode-data version.
- Query limits cap accepted characters and produced tokens. Whitespace-only and term-free queries
  fail explicitly instead of producing misleading rankings.
- Ranked hits retain exact corpus/chunk fingerprints, page and region coordinates, source text,
  matched lexical terms, stable rank order, and per-result content checksums.
- Binary relevance datasets bind judgments to one corpus. Evaluation rejects relevant chunk IDs
  outside that corpus and reports explicit fixed-cutoff Precision, Recall, MRR, MAP, and nDCG.
- Query results, datasets, and evaluations have strict canonical schema-v1 JSON, but PageTrace does
  not silently persist query text or metrics to artifact storage.

Retrieval scores measure lexical overlap, not truth, semantic equivalence, or answer support.
Queries and matched document text remain untrusted data and are never executed.

## Implemented Milestone 6 protections

- QA operates only on a validated retrieval result and introduces no language model, external
  service, parser, downloader, tool call, or document-instruction execution path.
- Answer text must equal exact character slices of retrieved hit text joined only by the configured
  separator. Every citation is rechecked against retrieval rank, chunk identity, offsets, matched
  query terms, and coverage during model construction and deserialization.
- The canonical result embeds the complete retrieval result, retaining document/corpus/chunk/page,
  coordinate, bounding-region, tokenizer, BM25, and query provenance needed to inspect a citation.
- Explicit typed configuration caps evidence items at 100 and answer text at 100,000 characters;
  defaults are three excerpts and 4,000 characters. Retrieval query limits remain in force.
- PageTrace abstains for no retrieval hits, insufficient unique query-term coverage, or an answer
  character limit that cannot preserve a supported excerpt. Abstention is a typed result, not
  fabricated fallback text.
- Strict canonical schema-v1 JSON rejects duplicate/unknown fields, malformed or non-finite values,
  changed evidence, unsupported answer text, checksum contradictions, and invalid state pairings.
- Questions, retrieved evidence, and answers are returned or serialized only when requested and
  are not silently persisted or sent to an external service.

Lexical overlap does not prove truth, completeness, entailment, or semantic relevance. Extracted
evidence may itself be wrong, malicious, out of context, or the result of an upstream extraction
error. Exact-source enforcement prevents unsupported generated wording; it does not validate the
source's claims.

## Implemented Milestone 7 protections

- Quality suites accept typed text metrics, integrity-checked retrieval evaluations and QA results,
  structured numeric human reviews, and an explicit policy. Nested canonical objects are fully
  revalidated during strict suite deserialization.
- Human reviews contain only safe case/review identifiers, a rubric version, and four integer
  scores from 1 to 5. The schema intentionally excludes reviewer identity and free-text notes.
- Static gates include explicit comparators, thresholds, and minimum sample floors. Missing metrics
  or insufficient samples become `not_evaluated` and make the report incomplete rather than pass.
- Baseline regression rules use a versioned higher/lower-is-better direction per supported metric.
  Missing baselines or samples are explicit; degradation beyond tolerance fails the report.
- Findings expose stable codes, dimensions, severities, and safe case IDs without reproducing
  source or answer text. Quality reports checksum every metric, gate, regression, and finding.
- The CLI accepts only regular non-symlink suite/baseline files, checks stable file size, and caps
  each canonical input at 512 MiB. Failed, incomplete, malformed, and successful evaluations have
  distinct exit behavior.
- Resource metrics count query tokens and retrieved/answer/evidence characters. The current local
  pipeline records zero external requests and zero estimated external-service cost; it does not
  invent CPU, memory, energy, latency, or monetary precision that is not measured.

Fixture scores and passing gates apply only to the supplied cases, judgments, policy, and processor
versions. They do not establish general correctness, truth, safety, fairness, privacy, or production
readiness. Suites embed QA results and therefore may contain sensitive questions and retrieved
document text; PageTrace does not silently persist or transmit them.

## Implemented Milestone 8 protections

- SQLite schema versioning rejects unknown or incomplete databases. Each operation uses a short
  transaction, and workers atomically claim the oldest queued job before executing it.
- Caller idempotency keys are syntax-bounded and uniquely bind to the workflow plus SHA-256 of the
  canonical request. A key replay with different content is rejected.
- Defaults cap canonical requests at 16 MiB, results at 32 MiB, queued jobs at 1,000, attempts at
  three, public error text at 1,000 characters, and lifecycle events at 1,000 per job.
- Explicit queued/running/succeeded/failed/cancelled states, ordered append-only events, terminal
  public errors, cooperative cancellation, and startup recovery prevent silent lifecycle loss.
- Built-in workflow adapters accept exact field sets, bind artifact storage and document input to
  operator-configured roots, reject source paths outside that input root, and do not interpret
  document content as commands.
- The built-in HTTP server binds only to loopback, requires a 32–512 character bearer token for
  every `/v1` route, compares credentials in constant time, rejects transfer encoding and
  duplicate JSON keys, requires bounded request lengths, and emits no tracebacks or request bodies.
- Responses disable caching and MIME sniffing, close the connection after each request, and expose
  only stable job metadata, results, public error codes, bounded events, and aggregate counters.
  Liveness and readiness endpoints intentionally return only a status word.
- The operator CLI reads its bearer token from a named environment variable rather than a command
  argument and separates database initialization, worker, and HTTP serving modes.

The SQLite database deliberately retains canonical requests and successful results. Those values
may contain paths, questions, evidence, answers, and quality suites, so its filesystem permissions,
backup policy, retention, and deletion are operator responsibilities. Bearer authentication does
not provide TLS, rotation, user identity, per-user authorization, audit identity, or rate limiting.
Running cancellation is cooperative at the handler boundary and cannot preempt an in-process
parser or computation. Startup recovery assumes one coordinated application instance; the current
schema does not provide distributed worker leases or heartbeats.

## Implemented Milestone 9 protections

- The browser application and API are served from the same loopback origin, so no cross-origin API
  permission is enabled. `/v1` routes retain the Milestone 8 bearer requirement.
- The bearer token is held only in JavaScript memory. The application does not place it in a URL,
  cookie, local storage, session storage, IndexedDB, logs, or rendered job metadata.
- Backend, document, answer, citation, finding, and event values are assigned through DOM text
  nodes. They are not inserted as HTML and cannot create executable markup in the interface.
- Static routing recognizes only `/`, `/index.html`, and generated single-segment `/assets/`
  names. Files must be bounded regular non-symlinks that resolve inside the configured web root.
- HTML disables caching; fingerprinted assets use immutable caching. Every web response disables
  MIME sniffing and referrer disclosure, blocks framing, limits browser capabilities, and applies a
  content security policy restricted to the same origin with objects and base URLs disabled.
- Evidence views keep exact citation offsets, chunk/page identity, retrieval rank, bounding-region
  coordinates, matched terms, and lexical coverage visible. Abstention is displayed explicitly,
  and coverage is described as lexical rather than a truth or completeness score.
- The interface stores recent job IDs only in the live page session. Reopening work requires a
  known canonical job ID; no unauthenticated or global job-list endpoint was added.

The frontend is not an authorization boundary. Any process or person holding the backend token can
read every retained job result exposed by that backend, and browser extensions, local malware, or a
compromised host may observe the token and displayed evidence. The built-in server still lacks TLS,
accounts, per-user authorization, request-rate limits, CSRF tokens, and remote deployment
hardening. Operators must keep it on loopback and protect the host, token, SQLite database,
artifact store, browser profile, and screen contents.

## Implemented Milestone 10 protections

- Every HTTP request requires exactly one Host header naming `127.0.0.1`, `::1`, or `localhost`
  on the actual listening port. An optional Origin must be one exact HTTP loopback origin on that
  port; duplicate, cross-origin, HTTPS, user-info, malformed, and wrong-port values are rejected.
- Accepted sockets receive a configurable 0.1-to-300-second timeout, defaulting to ten seconds, to
  bound stalled header/body reads. This timeout is not a workflow execution deadline.
- JSON and static responses add same-origin resource policy and anti-framing headers; JSON receives
  a non-executable content security policy. CORS remains disabled.
- A configurable retained-job ceiling defaults to 10,000. Exact idempotent replays remain readable
  at the ceiling, while submissions that would create another durable record fail explicitly.
- The operator CLI previews retention deletion by default and requires `--confirm` to mutate data.
  It selects a bounded oldest-first batch, deletes only succeeded/failed/cancelled jobs strictly
  older than an explicit cutoff, and relies on an atomic transaction plus foreign-key cascade for
  their events. Queued and running work is never selected. Database connections request SQLite
  secure deletion as defense in depth, without claiming physical erasure from WAL, snapshots,
  storage media, or backups.
- Dependabot checks Python, npm, and GitHub Actions weekly. CI actions are pinned to immutable
  reviewed commits, and CI audits resolved Python runtime dependencies and the locked frontend
  build dependency tree in addition to lint, tests, typing, packaging, and clean-wheel checks.
- The deployment runbook fixes the supported boundary at one trusted local operator, defines
  least-privilege storage/token/backup/monitoring/retention practices, and rejects remote or
  multi-user exposure. The incident runbook covers containment, secret rotation, evidence
  preservation, investigation, rebuild/restore, privacy deletion, and post-incident regression.
- Adversarial tests cover authority confusion and duplication, unsafe origins, connection-bound
  validation, retained-capacity behavior, purge cutoff/state preservation, and destructive CLI
  confirmation.

These controls reduce common local-web and operational failure modes; they do not turn PageTrace
into a remote production service. Purging a backend job does not delete the corresponding input,
content-addressed artifacts, logs, exports, screenshots, or backups. Operators must manage those
stores separately.

## Security principles

- Treat every document and all extracted content as untrusted data.
- Never treat document text as executable instructions, even when it resembles system, developer,
  tool, or user directions.
- Apply least privilege, explicit resource limits, deterministic processing, and auditable
  transformations as functionality is introduced.
- Minimize retention and external disclosure of sensitive documents.
- Make security properties measurable and test regressions as early as related behavior exists.

## Residual risks and future security work

Milestones 1 through 10 are in-process processing boundaries, not operating-system sandboxes.
Residual risks include vulnerabilities or pathological CPU/memory behavior in pypdf and
pdfplumber text/content-stream/layout parsing, Pillow, Python, or native image codecs; very large
decompressed text streams; deeply nested PDF object graphs; filesystem exhaustion; storage-root
tampering by a separate privileged process; and
source/storage mutation races. Existing byte/page/pixel bounds and repeated fingerprint checks
reduce exposure but cannot solve every denial-of-service or local-adversary scenario. Extraction
character limits bound accepted page output and cumulative canonical artifact size only after
`extract_text` returns. Malicious compressed/content streams may consume pypdf CPU or RAM before
that check. OCR pixel preflight does not prevent malicious PDFium, image-codec, RapidOCR, OpenCV,
or ONNX Runtime inputs from consuming CPU or memory before returning. OCR line and character limits
apply after inference. Structure span/table/cell limits apply after parser or inference work has
returned data. PageTrace does not claim CPU, memory, time, subprocess, parser, or inference
isolation. Corpus limits bound accepted output but construction and canonical serialization may
still consume memory proportional to the verified structured input. BM25 currently tokenizes the
complete bounded corpus for each query without persistent indexing or hard time/memory isolation.
Extractive QA scans and tokenizes returned hit text in-process without hard time/memory isolation;
its answer bounds limit accepted output rather than all intermediate work. Quality-suite parsing
and aggregation are also in-process; the CLI byte limit bounds accepted serialized input but not a
separate CPU, memory, or wall-clock sandbox. Backend request/result/queue/event/retained-record
limits bound accepted persistent data, not total database bytes, handler CPU or memory, disk use,
or workflow execution time. The HTTP socket timeout does not interrupt running work. SQLite and the
artifact store remain vulnerable to local privileged tampering, filesystem exhaustion, and
operator misconfiguration.

Future threat modeling and milestones will cover at least:

- malformed files and parser vulnerabilities;
- resource exhaustion beyond the current byte/page/pixel ceilings;
- unexpected embedded files, scripts, links, and active content;
- malicious or misleading document text;
- prompt injection against future model-assisted processing;
- confidential, regulated, or personally identifiable content; and
- unintended exposure to future external model or service providers.

Prompt injection is already a data-handling concern because PageTrace extracts untrusted text.
RapidOCR is a local purpose-built OCR model and its output remains untrusted data; no LLM, VLM, or
external model service consumes document content. Future model-provider disclosure, hard process
isolation, storage-byte quotas, remote/multi-user controls, and independently exercised disaster
recovery remain later responsibilities.

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
