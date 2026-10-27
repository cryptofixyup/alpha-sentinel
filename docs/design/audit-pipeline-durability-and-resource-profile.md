# Audit Pipeline Durability and Resource Profile

**Status:** Proposed baseline for implementation and review; not production approval  
**Parent design:** audit-sink-architecture-decision.md  
**Scope:** Failure model, PostgreSQL durability assumptions, initial test bounds, and approval gates  
**PR boundary:** PR #62 remains inspection-only and is not changed by this document.

## 1. Recommended first profile

Use PostgreSQL with a dedicated writer role and synchronous transaction commit. For a self-managed PostgreSQL deployment, verify rather than assume the relevant durability settings: `fsync=on`, `synchronous_commit=on`, and `full_page_writes=on`. Confirm that the underlying storage honors flush requests and that the selected managed service documents equivalent behavior if PostgreSQL settings are not directly configurable.

This profile is intended to protect acknowledged commits against ordinary PostgreSQL process failure and, subject to correct OS/storage behavior, local operating-system or host restart. A single-node commit acknowledgement does **not** by itself guarantee survival of permanent storage loss, loss of the database host, or regional failure. Do not claim those guarantees for this profile.

If surviving primary-node loss is required, select and verify synchronous replication and its acknowledgement policy before implementation. If surviving regional loss is required, define a separate multi-region recovery objective and test it; do not imply that a local transaction commit covers it.

## 2. Failure model

| Failure | Baseline treatment | Claim boundary |
|---|---|---|
| Application process crash after commit acknowledgement | Committed event should remain in PostgreSQL | Verify with integration/restart test |
| PostgreSQL process crash | Rely on configured transaction/WAL durability | Verify settings and restart recovery |
| OS/host restart or power loss | Depends on WAL flush and truthful storage flush semantics | Document infrastructure assumptions and test where feasible |
| Permanent storage/device loss | Not covered by single-node profile | Requires independent replica/backup and tested recovery |
| Primary host loss/failover | Not covered unless configured replication acknowledgement guarantees it | Requires an approved replication/failover profile |
| Regional loss | Not covered | Requires separate recovery-point and recovery-time objectives |
| Privileged database administrator tampering | Not prevented by database writer-role restrictions alone | Requires independent integrity/immutable-storage controls if in scope |
| Commit acknowledgement lost or timed out | Treat result as uncertain and reconcile by stable event ID | Never assert success or loss without evidence |

## 3. Initial test profile (not production thresholds)

Use the following as starting values for local integration and fault-injection tests only. Revisit using measured traffic and latency; do not present them as an SLA.

- Maximum request body: 1 MiB.
- Maximum serialized audit event: 16 KiB.
- Maximum in-flight audit writes: 32.
- Queue capacity: zero by default (direct bounded writes); if an implementation needs a queue, make it bounded and justify why it is safe.
- Database connection acquisition timeout: 250 ms.
- Audit transaction deadline: 1 second.
- Automatic retry: no blind retry after an ambiguous commit. Reconcile by stable event ID; only retry with the same ID under the defined idempotent insert contract.
- Shutdown drain: bounded to 2 seconds; remaining mandatory-audit requests must not be reported as successful without acknowledgement.
- Concurrency test: at least 100 concurrent requests, including sink latency, rejection, timeout, and restoration phases.
- Fault-injection repetitions: at least 100 per injected failure mode where deterministic and practical; record any test limitations.

These numbers are engineering test starting points, not validated performance or security limits. A 1-second transaction deadline must be measured against the actual deployment and may need adjustment before production.

## 4. Mandatory response invariant

For every request in mandatory-audit mode:

- A success response is permitted only after the corresponding audit event has received the configured commit acknowledgement.
- Sink connection failure, rejected insert, pool exhaustion, queue saturation, deadline expiry, or invalid acknowledgement produces a generic 503.
- No fallback to stdout/stderr or an unapproved secondary sink is allowed.
- An ambiguous commit timeout is not represented as a known failure-to-persist or known success; the caller receives the documented fail-closed response while the service reconciles safely.
- The service must not initiate a protected downstream side effect before mandatory audit commit.

This invariant does not mean that no request parsing or inspection code executes. It means no successful outcome or protected downstream side effect is authorized without the required audit commit.

## 5. Required implementation evidence

Before calling the profile accepted, capture:
1. Exact commit SHA and build/test commands.
2. Effective PostgreSQL durability settings or managed-service documentation.
3. Actual writer/reader/admin privileges, including inherited roles and ownership.
4. Integration tests against the selected PostgreSQL version and configuration.
5. Fault-injection results for slow, unavailable, rejected, and ambiguous commit paths.
6. Resource measurements under the documented concurrency test.
7. Restart/recovery evidence and an explicit statement of which failures were not tested.
8. Approved retention and any independent integrity/backup controls.

## 6. Approval gates before production

- Confirm that the stated local durability boundary matches the business/security requirement.
- Decide whether primary-host loss must be covered; if yes, define synchronous replication/failover semantics.
- Decide whether privileged-admin tampering must be detected and choose an independent control if required.
- Revisit test starting values using measured traffic, resource limits, and latency.
- Approve retention, backups, restore drills, access roles, and legal/contractual requirements.

Until these gates are met, this profile is a proposed implementation baseline, not a production guarantee.

**Checks are evidence. Release acceptance is a separate decision.**
