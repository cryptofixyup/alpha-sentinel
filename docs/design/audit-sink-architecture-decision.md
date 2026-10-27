# Audit Sink Architecture Decision Record

**Status:** Proposed decision for review; not an implemented or tested runtime design  
**Decision scope:** First audit sink implementation for the guardrail proxy  
**Related documents:** audit-events-sensitive-data-redaction.md, audit-sink-failure-retention-policy.md, audit-sink-implementation-threat-model.md, audit-pipeline-threat-model-matrix-and-acceptance-tests.md  
**PR boundary:** PR #62 remains inspection-only and is not modified by this decision.

## 1. Decision summary

Recommend PostgreSQL as the initial audit sink, using a dedicated least-privilege writer identity, a versioned typed event schema, bounded synchronous writes, and a mandatory-audit mode that returns success only after the sink's configured commit acknowledgement is verified.

This is a proposed architecture baseline, not a claim that PostgreSQL has been configured, that a connector exists, or that durability or performance has been tested. Implementation should begin only after the deployment failure model and database durability settings are approved.

## 2. Why PostgreSQL first

PostgreSQL provides transactional inserts, unique constraints for idempotency, mature role-based permissions, and well-understood transaction semantics. It is a practical first implementation when the application already operates or can operate a managed PostgreSQL service.

Trade-offs:
- Audit writes add latency and make successful responses dependent on sink availability in mandatory mode.
- Database configuration and storage/replication semantics determine which failures a commit acknowledgement survives.
- Database administrators may retain capabilities to alter or delete records; a database table alone is not immutable storage.
- Cross-region resilience and tamper evidence require explicit configuration and may need additional controls.
- A commit timeout can leave the client uncertain whether the transaction committed; stable event identity and reconciliation are required.

If PostgreSQL is unavailable in the deployment environment or its administrative trust model is unacceptable, revisit this decision before implementation rather than silently substituting another backend.

## 3. Proposed event-write contract

1. Validate request bounds and run the inspection decision.
2. Construct an audit event exclusively from trusted server-side decision metadata and allowlisted values. Never copy raw request/response content or arbitrary headers into the event.
3. Assign a server-generated event ID and request ID. The event ID is stable across retries of the same logical event.
4. Insert the event using a dedicated writer identity and a parameterized statement.
5. Await a successful transaction commit acknowledgement under the approved database durability configuration.
6. Return the successful inspection response only after the required acknowledgement.
7. If connection, insert, constraint, commit, or deadline handling fails, return a generic 503 in mandatory mode. Do not write sensitive diagnostic details to stdout/stderr or an unapproved fallback sink.
8. If a timeout occurs after the database may have committed, treat the result as uncertain. Reconcile by stable event ID or use a documented idempotent retry strategy; do not assert either loss or success without evidence.

The audit write records the decision; it does not authorize additional side effects. No upstream forwarding is introduced by this design.

## 4. Durability contract — decisions required

A PostgreSQL commit acknowledgement is meaningful only relative to the selected configuration and failure model. Before claiming durability, explicitly decide and record:

- Local process crash: must a committed event survive application process failure?
- Database process/host crash: which PostgreSQL and storage guarantees are required?
- Operating-system or power loss: which WAL flush and storage guarantees are required?
- Storage-device loss: are backups or replicas required, and what recovery point is acceptable?
- Primary-node loss/failover: synchronous or asynchronous replication? What acknowledgement level is required?
- Regional loss: is this in scope, and what recovery point/time objectives apply?
- Administrative compromise: which roles can alter history, and is an independent immutable or cryptographically verifiable copy required?

Do not claim survival of host, device, failover, or regional failure unless the configuration and tests support that exact claim. Document PostgreSQL settings, managed-service semantics, storage assumptions, replication mode, and backup policy in deployment evidence.

## 5. Resource limits and failure policy

The following values are placeholders to be measured and approved, not preselected production thresholds:

- Maximum request size and maximum serialized event size.
- Maximum concurrent audit writes and any bounded queue capacity.
- Connection-pool size and acquisition timeout.
- Per-write/transaction deadline.
- Retry budget and backoff.
- Maximum in-flight work during shutdown.
- Load-test concurrency and expected traffic profile.

Mandatory mode must fail closed when it cannot obtain the configured commit acknowledgement within the approved deadline. It must not buffer indefinitely or fall back to stdout/stderr. A health endpoint may report aggregate sink health and bounded counters without request content or per-request secrets.

## 6. Database access model

Proposed roles:
- **audit_writer:** insert only into the approved audit interface; no select/list/update/delete/truncate/schema ownership.
- **audit_reader:** read only approved fields and ranges, granted to named authorized principals.
- **audit_admin:** narrowly scoped operational administration, separate from the application identity, with monitored and reviewed exceptional actions.
- **migration_owner:** used only for controlled schema migrations, not by the running service.

Validate actual effective permissions, including inherited roles, table ownership, schema privileges, sequence privileges, security-definer functions, and administrative paths. PostgreSQL permissions do not prevent a sufficiently privileged database administrator from altering data. If protection against privileged tampering is a requirement, add and test a separate integrity/immutability control.

## 7. Idempotency and ambiguous commits

- Assign an immutable event ID before attempting persistence.
- Enforce a unique constraint on event ID.
- Reuse the same event ID when retrying the same logical event.
- Distinguish a definite transaction failure from an unknown commit outcome.
- On unknown outcome, reconcile by event ID or perform a safe idempotent insert under the documented transaction contract.
- Define whether duplicate delivery is counted, ignored, or reported; never silently rewrite an existing event.
- Do not claim exactly-once delivery solely because a unique constraint exists. State the actual guarantees and failure assumptions.

## 8. Acceptance gates before release

1. Approve the deployment failure model and durability configuration.
2. Approve resource limits, deadlines, retry semantics, and the mandatory-audit scope.
3. Implement the typed event builder and PostgreSQL adapter on a separate branch.
4. Add schema, canary, permissions, outage, slow-sink, queue-saturation, concurrency, cancellation, restart, and ambiguous-commit tests.
5. Run integration and fault-injection tests against a real isolated PostgreSQL instance configured to match the intended deployment, not mocks alone.
6. Verify the effective database privileges and any selected tamper-evidence controls.
7. Record exact commit SHA, configuration, test commands/results, and infrastructure assumptions.
8. Conduct independent review and make release acceptance a separate decision.

**Checks are evidence. Release acceptance is a separate decision.**
