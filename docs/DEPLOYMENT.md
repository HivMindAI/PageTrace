# Deployment and Operations

PageTrace is a single-host inspection product. Its supported topology is one trusted operator,
one operating-system account, a loopback-only HTTP server, and local SQLite/artifact storage. It
is not a remotely exposed, multi-user, or multi-tenant service.

## Supported topology

```text
trusted local browser
        |
        | http://127.0.0.1:8765
        v
PageTrace web/API process ---- SQLite database
        |
        `--------------------- content-addressed artifact store
```

The built-in server accepts only `127.0.0.1`, `::1`, or `localhost`. It rejects Host and Origin
authorities that are not loopback or that name a different port. Do not bind, forward, tunnel, or
publish it to an untrusted network. A remote reverse-proxy deployment is outside the supported
boundary because PageTrace does not provide TLS, user accounts, per-user authorization, audit
identity, distributed worker leases, or hard process isolation.

## Pre-deployment checklist

- Run PageTrace under a dedicated, unprivileged operating-system account.
- Put the database, artifact store, input root, and logs in separate operator-controlled
  directories. Grant access only to the service account and authorized administrators.
- Keep the input root narrow. Ingestion requests can name only regular non-symlink files beneath
  that root, but every file placed there is still untrusted parser input.
- Generate a unique high-entropy bearer token, store it in the service manager or secret store,
  and expose it only through `PAGETRACE_BACKEND_TOKEN`. Never place it in an argument, URL,
  repository file, screenshot, or issue report.
- Choose a retained-job ceiling that fits the privacy policy and available disk. The default is
  10,000 records; reaching it rejects new non-idempotent submissions instead of silently deleting
  evidence.
- Review [SECURITY.md](../SECURITY.md), especially the parser, native-code, filesystem, and
  in-process resource-exhaustion risks.

## Initialize and run

```bash
pagetrace-backend \
  --database /protected/pagetrace/backend.sqlite3 \
  --store /protected/pagetrace/artifacts \
  --input-root /protected/pagetrace/incoming \
  --max-retained-jobs 10000 \
  init

pagetrace-backend \
  --database /protected/pagetrace/backend.sqlite3 \
  --store /protected/pagetrace/artifacts \
  --input-root /protected/pagetrace/incoming \
  --max-retained-jobs 10000 \
  serve --host 127.0.0.1 --port 8765 --connection-timeout 10
```

Use the service manager to restart on failure, apply an operating-system memory/CPU limit where
available, and stop the process cleanly before host shutdown. The HTTP connection timeout bounds
slow or stalled request sockets; it does not impose a deadline on document parsing or workflow
execution.

Probe `GET /healthz` for process liveness and `GET /readyz` for database readiness. Neither route
contains document data. Alert on repeated restarts, readiness failures, retained-capacity errors,
unexpected disk growth, filesystem errors, or dependency-audit failures.

## Retention and deletion

The database can contain source paths, questions, retrieved evidence, answers, quality suites,
public errors, and lifecycle events. Define a retention period before processing sensitive data.

Preview a bounded deletion batch first:

```bash
pagetrace-backend --database /protected/pagetrace/backend.sqlite3 \
  purge --older-than-hours 168 --limit 1000
```

After checking the cutoff and count, perform the permanent deletion:

```bash
pagetrace-backend --database /protected/pagetrace/backend.sqlite3 \
  purge --older-than-hours 168 --limit 1000 --confirm
```

Purge processes terminal jobs oldest-first and cascades their lifecycle events. It never deletes
queued or running jobs. Repeat bounded batches as needed. Deleting a backend job does not delete
content-addressed document artifacts, input files, logs, exports, browser screenshots, or backups;
manage each of those stores under its own retention policy.

PageTrace requests SQLite secure deletion on each database connection so deleted cell content is
overwritten when SQLite releases it. This is defense in depth, not a forensic-erasure guarantee:
WAL data, filesystem journals, snapshots, SSD wear-leveling, and backups can retain earlier copies.
Use storage-specific sanitization procedures when policy requires physical erasure.

## Backup, restore, and upgrade

- Use a SQLite-aware online backup, or stop every PageTrace process before copying the database and
  its `-wal`/`-shm` companions. Copying only the main file while writers run is not a valid backup.
- Back up the artifact store and database as one recovery set. Encrypt backups, restrict access,
  define expiry, and test restoration into an isolated directory.
- Before an upgrade, review the changelog and dependency changes, run the complete validation
  suite, take a tested backup, and stop workers. PageTrace rejects unknown database schemas rather
  than migrating silently.
- Roll back by stopping the new process and restoring the complete pre-upgrade recovery set. Do not
  mix a restored database with artifacts from a different point in time without verification.

Use [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md) when compromise, unauthorized disclosure,
integrity failure, malicious dependency, or sustained denial of service is suspected.
