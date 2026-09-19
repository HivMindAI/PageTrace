# Incident Response

This runbook covers the local PageTrace service, its bearer token, SQLite database, artifact and
input stores, generated exports, logs, backups, build environment, and dependency chain. Assign an
incident owner and record every action with UTC timestamps. Do not put secrets or real sensitive
documents in public issues or chat systems.

## 1. Triage

Treat an event as a security incident when it may involve unauthorized document/result access,
token exposure, tampered artifacts or database records, a malicious dependency or build, parser
exploitation, unexpected network exposure, or resource exhaustion that affects availability.

Record the detected time, affected revision and host, current process state, observable indicators,
suspected data classes, and who has been notified. Prefer hashes, safe identifiers, and minimal
reproductions over copying document contents.

## 2. Contain

1. Stop accepting new input and stop the PageTrace server and workers. If active exploitation is
   suspected, isolate the host from the network before further inspection.
2. Revoke the bearer token at its secret store and remove it from the affected process environment.
   Do not reuse that token.
3. Preserve volatile process, connection, and service-manager information when safe. Capture
   read-only copies of relevant logs, the database plus WAL/SHM files, artifacts, configuration,
   dependency manifests/lockfiles, installed-package inventory, and exact application revision.
4. Hash preserved evidence and restrict it to responders. Do not run purge, vacuum, cleanup, or
   dependency upgrades until the evidence decision is recorded.
5. If the repository or build identity may be compromised, suspend releases and automation
   credentials separately from the PageTrace bearer token.

## 3. Investigate and assess exposure

- Establish the earliest plausible compromise and the affected hosts, tokens, jobs, documents,
  artifacts, exports, logs, backups, users, and downstream copies.
- Compare stored identities and fingerprints against known-good inputs. PageTrace integrity checks
  detect many contradictions, but a privileged local attacker may replace multiple related files.
- Review service binds, forwarding/tunnel configuration, Host/Origin rejection logs, readiness
  failures, queue/capacity behavior, filesystem growth, process crashes, and dependency changes.
- Determine whether legal, contractual, organizational, or data-subject notification duties apply.
  The repository does not define those obligations for an operator.

## 4. Eradicate and recover

1. Rebuild from a trusted operating system and verified source/dependency set when host or build
   integrity is uncertain. Do not treat an in-place reinstall as proof that compromise is gone.
2. Patch the root cause, rotate every exposed secret, and review filesystem permissions and service
   configuration. Keep the built-in server loopback-only.
3. Restore the database and artifact store from one verified recovery point, or initialize clean
   storage when retained data cannot be trusted. Validate readiness and representative artifact
   readback before processing new input.
4. Run lint, typing, tests, package validation, frontend checks, and dependency audits. Exercise the
   malicious reproduction only in an isolated environment with synthetic data.
5. Resume in stages, watch health/readiness, disk use, capacity errors, crashes, and relevant
   indicators, then close containment only after the incident owner accepts the evidence.

## 5. Privacy deletion and communication

After preservation and notification decisions are complete, use the bounded purge command for
eligible terminal jobs. Separately remove affected inputs, artifacts, exports, logs, browser data,
and backups according to policy. Record what was deleted, what remains, why, and when remaining
copies will expire. A backend purge alone is not a complete erasure workflow.

Send factual updates that distinguish confirmed impact from hypotheses. Share the affected
revision, safe indicators, mitigations, and upgrade/rotation requirements. Use the private
vulnerability-reporting guidance in [SECURITY.md](../SECURITY.md) for product vulnerabilities.

## 6. Post-incident review

Within the operator's chosen review window, document the timeline, root cause, control successes
and failures, data affected, recovery result, and accountable follow-up work. Add a regression test
for the smallest safe reproduction, update this runbook and the deployment checklist, and verify
that every follow-up has an owner and completion criterion.
