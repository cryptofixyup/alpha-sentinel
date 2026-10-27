# Decision Record: Audit Sink Failure, Retention, and Access

**Status:** Proposed — requires security/operational owner approval  
**Scope:** Future audit-event persistence only  
**Prerequisite:** `docs/design/audit-events-sensitive-data-redaction.md`  
**Current behavior:** No audit sink is implemented by this decision record. PR #62 remains inspection-only.

## 1. Decision summary

Proposed initial policy for any future deployment that declares audit events mandatory:

1. **No silent loss:** do not return a successful inspection response until the required audit event has been accepted by the configured sink at the durability level promised by that sink.
2. **Fail closed on audit failure:** if the sink is unavailable, rejects the event, reaches a configured capacity limit, or cannot confirm the required durability before the deadline, return a generic service-unavailable response. Do not report an allow decision to the caller when the mandatory audit record was not committed.
3. **No fallback to stdout/stderr:** never route audit records or raw request data to a fallback logger. The fallback path must not include the event payload or sensitive error details.
4. **Bound all resources:** bounded request body, bounded event size, bounded queue/buffer if one is used, bounded write deadline, and explicit overload behavior. No unbounded in-memory queue.
5. **Make failure observable without content:** expose a counter/health state such as `audit_sink_write_failures_total` and `audit_sink_healthy`; do not attach request bodies, credentials, request IDs, rule signatures, or arbitrary error strings as metric labels.
6. **Do not claim durable audit:** a successful in-memory enqueue is not a durable commit. The selected sink must define what acknowledgement means (e.g. append acknowledged by the local filesystem versus replicated storage acknowledgement).

This is a proposed strict profile, not an implemented or approved production policy. A deployment that chooses best-effort logging must explicitly document that audit gaps are possible and must not claim mandatory audit completeness.

## 2. Request/decision behavior

| Condition | Proposed response behavior | Required observability |
|---|---|---|
| Inspection completes and audit commit succeeds | Return the normal inspection result | Increment non-sensitive decision/outcome metrics |
| Sink unavailable or write rejected | Return generic 503; do not expose sink details | Health degraded; increment bounded failure counter |
| Write acknowledgement misses configured deadline | Return generic 503; treat commit status as unknown | Health degraded; increment timeout counter |
| Buffer/queue reaches capacity | Do not enqueue unboundedly; reject with generic 503 | Increment queue-full counter; health degraded |
| Sink recovers | Resume only after health check; do not replay unbounded volatile records | Recovery transition observable without request content |
| Process crashes before commit | No success response should have been sent for that uncommitted event under the strict profile | Crash diagnostics must not include payloads |
| Process crashes after commit but before response | A duplicate observation may be possible on retry; request IDs are not caller-controlled idempotency keys | Document and test duplicate-event semantics |

### Transaction ordering

For the strict profile, the order is:

1. Generate server-side request ID and inspect bounded request data in memory.
2. Construct the allowlisted metadata-only event.
3. Submit the event to the configured sink and wait for the documented commit acknowledgement, within a fixed deadline.
4. Only after acknowledgement, return the inspection decision.

If step 3 fails or times out, return a generic 503. A timeout can leave commit status uncertain; do not claim the event definitely was or was not persisted. The service must not log the raw event source or sink error while handling this path.

**Important consequence:** synchronous audit persistence can add latency and reduce availability. This is intentional for the strict profile and must be measured before production use. A buffered design is acceptable only if its durability and loss window are explicitly defined; an enqueue acknowledgement must not be described as durable commit.

## 3. Sink and diagnostic controls

Before implementation, select and document:

- Sink type and location; local file, remote collector, or database have different failure and durability semantics.
- Writer identity and least-privilege permissions; service should not have broader read/delete access than necessary.
- Encryption at rest/in transit where applicable, key ownership, rotation, and recovery.
- Atomic record framing and behavior for partial writes, truncated records, disk-full, permission errors, and corrupted files.
- File rotation or partitioning; prevent symlink/path substitution and unsafe file permissions if local files are selected.
- Whether events are authenticated/integrity-protected in transit and how unauthorized modification/deletion is detected.
- Operational health signals and alert thresholds; metrics must remain low-cardinality and content-free.
- Dependency logging configuration, panic hooks, and crash-reporting configuration. These are part of the threat surface, not assumed safe by default.

A sink failure diagnostic may contain a fixed error code and component name from a static allowlist. It must not contain exception text, filesystem paths, connection strings, environment values, payload fragments, or credentials.

No automatic “log it somewhere else” fallback is permitted. If a secondary sink is later approved, it requires its own access, redaction, retention, and failure semantics.

## 4. Retention and deletion proposal

**Proposed starting point for owner review: 30 calendar days of searchable audit events**, with shorter retention preferred where the operational purpose permits. This is a proposal, not a legal conclusion or approved retention period. The final duration must be based on incident-response needs, contractual commitments, and applicable law.

Required controls:

- Configure retention explicitly; no indefinite retention by default.
- Enforce automatic expiry and verify it with tests.
- Define whether expiry is measured from event timestamp or ingestion time; prefer trusted sink ingestion time for retention enforcement.
- Include rotated files, replicas, exports, backups, and disaster-recovery copies in the deletion schedule.
- Restrict exports and downloads; exporting events must not create an uncontrolled second retention domain.
- Record administrative access and retention-policy changes in a separate protected administrative audit trail, without recursively logging sensitive event content.
- Document exceptions/holds, approval authority, expiry date, and release process. Do not silently suspend deletion.
- Periodically test expiry and deletion, including rotated and backup copies.

The event schema deliberately omits prompts, tokens, raw headers, body hashes, and content fingerprints to minimize the impact of retained records.

## 5. Access-control model

Minimum proposed roles:

- **Writer:** service identity may append events; cannot list, read, rewrite, or delete existing events except where the chosen sink technically requires narrower documented permissions.
- **Reader/investigator:** named, authenticated operators with a defined incident-response purpose; read access is logged.
- **Retention administrator:** may change retention only through reviewed configuration; cannot silently erase the administrative record of the change.
- **Platform administrator:** infrastructure access is separately controlled and audited; root-equivalent access is not treated as equivalent to application-level authorization.

Use least privilege, protected credentials, rotation, and separation of duties where available. Do not put secrets in configuration examples, deployment logs, or health responses.

## 6. Required failure-injection and acceptance tests

- [ ] Sink unreachable before request.
- [ ] Sink rejects a write.
- [ ] Write hangs beyond the configured deadline.
- [ ] Disk full / quota exceeded (for file-backed sinks).
- [ ] Permission denied and partial/truncated write.
- [ ] Queue full, if a queue is selected; memory remains bounded.
- [ ] Process restart/crash at each boundary: before write, during write, after commit and before HTTP response.
- [ ] Sink recovery does not replay unbounded or stale in-memory events.
- [ ] No successful inspection response is returned before the strict profile's commit acknowledgement.
- [ ] No raw prompt, body, header, token, secret, exception string, path, or connection string appears in stdout/stderr, audit records, tracing, metrics, panic output, or failure responses.
- [ ] Retention expiry covers active storage, rotations, replicas, and backups as documented.
- [ ] Access-control tests prove the writer cannot read/delete records and unauthorized readers are denied.
- [ ] Operational metrics are bounded, content-free, and do not use request IDs as labels.

Use synthetic canary secrets only. Tests must capture all relevant output streams and sink artifacts.

## 7. Explicit open decisions

These must be approved before implementation:

1. Whether the deployment requires the strict fail-closed audit profile or explicitly accepts best-effort logging.
2. Sink technology and the exact durability acknowledgement.
3. Write deadline and any queue/buffer policy.
4. Final retention duration (30 days is only the proposal).
5. Required encryption, integrity protection, replication, backup and deletion guarantees.
6. Authorized reader and administrator roles.
7. Applicable contractual and legal retention requirements.

## 8. Release boundary

This decision record changes no runtime behavior and does not add a sink. PR #62 remains inspection-only. A future implementation requires a separate change, threat model, failure-injection tests, redaction tests, and explicit approval of the open decisions above. Upstream forwarding remains a separate design and implementation phase.
