# Audit Pipeline Operational Gates — Proposed Baseline

**Status:** Proposed implementation profile; approval and deployment validation still required  
**Parent:** audit-pipeline-durability-and-resource-profile.md  
**Backend:** PostgreSQL, as proposed in audit-sink-architecture-decision.md  
**PR boundary:** PR #62 remains inspection-only; this document does not change its code or status.

## 1. Decisions proposed

### Failure model

Adopt a local durable-commit baseline for the first implementation:

- An acknowledged audit transaction must survive application process failure and PostgreSQL process recovery.
- Host/OS restart survival is required only under verified WAL flush, filesystem, and storage guarantees.
- Permanent storage loss, host loss without a suitable replica, primary failover, and regional loss are not covered by a single-node commit acknowledgement.
- If the product requirement includes host or storage loss, configure and test independent replication and recovery before claiming that guarantee.
- A successful response in mandatory-audit mode is allowed only after the configured transaction commit acknowledgement. On timeout or lost acknowledgement, report a generic failure and reconcile the uncertain outcome using the stable event ID.

For self-managed PostgreSQL, require and verify `fsync=on`, `synchronous_commit=on`, and `full_page_writes=on` as the baseline, subject to review of the selected PostgreSQL version and environment. For managed PostgreSQL, capture provider documentation or equivalent configuration evidence. These settings do not compensate for storage that falsely reports flush completion and do not imply replication or regional durability.

### Operational limits

Use the following as initial test/development bounds, not production SLAs:

| Parameter | Initial value | Rationale / qualification |
|---|---:|---|
| Maximum request body | 1 MiB | Protects parser and request memory; adjust to actual endpoint contract |
| Maximum serialized audit event | 16 KiB | Keeps event records small and bounded |
| Maximum concurrent audit writes | 32 | Starting concurrency ceiling; validate against connection pool and service load |
| Queue capacity | 0 by default | Prefer bounded direct writes initially; if a queue is required, it must have a finite capacity and explicit full-queue behavior |
| Connection acquisition timeout | 250 ms | Initial fault-test bound; measure against the chosen deployment |
| Audit transaction deadline | 1 second | Initial test bound, not a production latency promise |
| Blind retries after ambiguous commit | 0 | Reconcile by event ID; retry only under a documented idempotent insert contract |
| Shutdown drain deadline | 2 seconds | Bound shutdown; no pending mandatory-audit request may be reported as successful without acknowledgement |
| Concurrency test | At least 100 simultaneous requests | Include slow sink, saturation, outage, recovery, and cancellation phases |

Do not silently increase deadlines, queue capacity, or retries to make tests pass. Change them only with workload evidence and an updated documented decision. The initial values may prove too strict for production; measure before setting production thresholds.

### Tamper resistance

Treat database role separation as necessary but insufficient against a privileged database administrator.

- Runtime `audit_writer` identity: insert-only access to the approved audit interface; no read, update, delete, truncate, schema ownership, or administration.
- Separate reader and administrative identities; administrative actions require explicit elevated credentials and controlled review.
- Add cryptographic tamper evidence if protection against privileged alteration is in scope: canonicalize the approved audit event representation, chain event digests in a defined order, and periodically sign a checkpoint.
- Keep checkpoint signing keys outside the database trust boundary, preferably in a KMS/HSM or separate signing service. Store signed checkpoints in an independent append-only or immutable destination controlled by a separate security boundary.
- Verify checkpoints independently and alert on missing, reordered, truncated, or modified records.
- Do not claim that a hash chain stored only in the same database prevents a privileged DBA from rewriting the records and recomputing the chain. The independently protected signed checkpoint is the trust anchor.
- Never hash or log raw request bodies, prompts, credentials, or tokens as part of this design. Integrity applies to the approved audit event only; the event schema remains data-minimized.

Cryptographic sealing detects tampering only relative to protected checkpoints and key security. It does not prevent deletion of uncheckpointed recent events, prove who performed an alteration, or guarantee availability. Define checkpoint frequency and the maximum acceptable detection window before release.

## 2. Mandatory failure behavior

For mandatory-audit requests:

1. Validate bounded request input and calculate the inspection decision.
2. Construct a typed event from allowlisted server-derived fields.
3. Persist with the approved event ID and wait for the configured commit acknowledgement.
4. Return success only after acknowledgement.
5. On sink unavailable, connection pool exhaustion, rejected insert, queue saturation, transaction deadline, or invalid acknowledgement, return a generic 503.
6. On ambiguous commit, fail closed for the request and reconcile by stable event ID. Do not issue an unsafe duplicate or claim a known persistence outcome without evidence.
7. Never redirect audit data or exceptions to stdout/stderr or an unapproved fallback sink.

The invariant prevents success and protected downstream side effects before mandatory audit commit. It does not imply that no request parsing or inspection code executes.

## 3. Acceptance evidence

Before implementation is accepted, require:

- Effective PostgreSQL durability settings and storage/managed-service assumptions recorded.
- Integration tests against a PostgreSQL instance configured like the target deployment.
- Fault injection for process restart, connection loss, slow writes, rejected writes, deadline expiry, pool exhaustion, queue saturation, cancellation, and ambiguous commits.
- Verification of effective database privileges, including inherited roles, ownership, schema permissions, and administrative paths.
- Canary tests across stdout, stderr, logs, tracing, metrics, persisted records, and captured sink traffic.
- Concurrency tests showing bounded resources and no success response without commit acknowledgement.
- If cryptographic sealing is enabled: reproducible event canonicalization, chain/checkpoint verification, signing-key separation, tamper/truncation tests, and independent checkpoint storage.
- Exact commit SHA, commands, configuration, environment assumptions, results, and known untested failure modes.
- Separate release-acceptance decision; a green CI run alone is insufficient.

## 4. Open production decisions

The following must be explicitly approved before making production guarantees:

1. Whether primary-host/storage loss must be survived, and the required recovery point/time objectives.
2. Whether synchronous replication is required and which acknowledgement/failover policy is appropriate.
3. Measured production request rate, event rate, payload distribution, latency budget, and resource envelope.
4. Production deadlines, concurrency, connection-pool sizing, queue behavior, and retry policy based on measurements.
5. Cryptographic checkpoint interval and maximum acceptable tamper-detection window.
6. KMS/HSM or separate signing-service choice, checkpoint retention, access roles, and recovery procedure.
7. Retention, backups, restore tests, legal/contractual requirements, and authorized deletion workflow.

Until these are approved and validated, this is a proposed engineering baseline, not a production durability or tamper-resistance guarantee.

**Checks are evidence. Release acceptance is a separate decision.**
