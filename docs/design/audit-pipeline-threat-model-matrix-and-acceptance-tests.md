# Audit Pipeline Threat Model Matrix and Acceptance Test Plan

**Status:** Proposed specification; not runtime implementation or test evidence  
**Scope:** Audit event construction, sink delivery, failure handling, integrity, and access control  
**Related design:** audit-events-sensitive-data-redaction.md, audit-sink-failure-retention-policy.md, and audit-sink-implementation-threat-model.md  
**Boundary:** Does not expand PR #62 beyond its inspection-only prototype scope.

## 1. Security objectives

1. Audit events contain only approved, typed, allowlisted metadata.
2. Mandatory audit mode never returns success unless the configured sink's documented durability boundary has been acknowledged.
3. Sink failure is bounded and fail-closed; no unapproved fallback output is permitted.
4. Persisted records resist unauthorized alteration and deletion to the degree supported by the selected storage design.
5. Concurrent requests observe consistent breaker state and bounded resource use.
6. Service write credentials cannot read, alter, or delete historical records unless those capabilities are explicitly required and separately authorized.

## 2. Threat model matrix

| Threat ID | Threat vector | Impact | Required mitigation | Acceptance evidence |
|---|---|---|---|---|
| **TM-01** | Secret or prompt exfiltration through audit payloads, logs, traces, metrics, panic output, or sink errors | Exposure of prompts, API tokens, session secrets, request bodies, credentials, or sensitive headers | Strict typed schema and field allowlist; construct events from trusted decision metadata only; prohibit raw request/response content and free-form exceptions; synthetic canary tests across every output path. Pattern matching is supplementary detection, not the primary safeguard. | Canary test report and output scan for stdout, stderr, application logs, tracing, metrics, persisted files, and captured network sink payloads; no canary occurrence |
| **TM-02** | Denial of service through sink exhaustion, disk exhaustion, slow writes, queue saturation, or request flooding | Unbounded memory growth, worker starvation, process instability, or audit bypass | Bounded queue and concurrency; request-size limits; per-write deadlines; backpressure; bounded retries; generic fail-closed 503 when mandatory audit cannot be committed; no unbounded buffering or synchronous indefinite waits | Fault-injection and load results showing bounded resources, bounded request completion time, and no successful response when mandatory commit fails |
| **TM-03** | Log tampering or unauthorized mutation by a compromised process, operator, or local user | Historical evidence is altered or deleted, undermining incident investigation and accountability | Separate writer and administrator identities; append-only/write-only permissions where supported; immutable/WORM storage where required; integrity chaining or signed checkpoints if selected; controlled and logged administrative exceptions | Role/permission tests, tamper-detection test, and evidence of storage configuration; claims limited to controls actually configured |
| **TM-04** | Race conditions during sink failure or circuit-breaker state changes | Concurrent requests may return success or wait indefinitely while the sink is unavailable | Define breaker states and transitions; use synchronization/atomic state with documented memory-ordering and transition semantics; make admission and mandatory commit checks consistent; fail closed while unavailable; test concurrent transition and recovery behavior | Deterministic concurrency tests and stress tests demonstrate no successful response without commit acknowledgement and no unbounded waits during outage |

## 3. Acceptance test cases

All tests below are required for the corresponding controls before implementation acceptance. Record the exact commit SHA, sink adapter and configuration, test command, environment assumptions, result, and relevant logs. Never include actual secrets in test reports. These tests are a plan until executed.

### AT-01 — Canary leakage across output channels (TM-01)

**Setup**
- Use synthetic canary TEST_SECRET_7F31 plus a generated high-entropy marker.
- Place canaries in representative untrusted inputs, such as a request body, header, and injected sink exception message. Use synthetic values only.
- Capture stdout, stderr, application logs, tracing, metrics, persisted audit records, and network sink payloads in an isolated test environment.

**Assertions**
- The audit event contains only approved schema fields and allowlisted values.
- Zero occurrences of either canary appear in any captured audit or diagnostic output.
- No raw body, body excerpt, credential, arbitrary header, exception string, or stack trace is persisted.
- A schema violation is rejected or mapped to a fixed safe error; it does not cause raw input to be logged.

**Pass condition:** All channels are scanned and report zero canary matches. A test that inspects only the final audit record is insufficient.

### AT-02 — Sink outage, unresponsiveness, and fail-closed response (TM-02, TM-04)

**Setup**
- Exercise sink unavailable, connection refused, write rejected, delayed response, dropped acknowledgement, queue full, and deadline exceeded.
- Configure an explicit write deadline and mandatory audit mode.

**Assertions**
- No request receives a successful response unless the configured durability acknowledgement is verified.
- Failure is surfaced as a generic 503 Service Unavailable within the documented deadline and response margin.
- No request waits indefinitely.
- The response contains no sink address, exception text, stack trace, credentials, or internal diagnostic detail.
- An acknowledgement that means only “enqueued” does not satisfy the durable-commit requirement.
- Where timeout leaves commit status uncertain, the system does not falsely report a known commit outcome; retry/idempotency behavior follows the documented contract.

**Clarification:** “Without processing” means no protected success or downstream side effect may be authorized before mandatory audit commit. The service may need to parse and inspect the request to produce a decision; the test must not imply that no code at all executes.

### AT-03 — No fallback leakage on primary sink failure (TM-01, TM-02)

**Setup**
- Make the primary sink fail at each supported failure point.
- Capture stdout/stderr and inspect configured secondary outputs.

**Assertions**
- No audit event, request content, secret, or exception detail is redirected to stdout/stderr.
- No secondary sink is used unless it is explicitly approved in the design and meets the same security/durability contract.
- A mandatory-audit request fails closed when the approved sink cannot commit.
- Health signals are aggregate and bounded; they do not contain request IDs or payload data unless explicitly approved.

**Pass condition:** No unapproved fallback path is invoked and no canary is found in captured fallback channels.

### AT-04 — Concurrent load, backpressure, and breaker consistency (TM-02, TM-04)

**Setup**
- Generate concurrent requests while throttling or pausing sink writes, filling the bounded queue, and inducing intermittent failures.
- Repeat across breaker open, half-open/recovery (if implemented), and closed states.

**Assertions**
- Queue size, memory use, active writes, retries, and request duration remain within documented bounds.
- When mandatory audit cannot be committed, requests fail closed; no race permits a successful response without commit acknowledgement.
- Breaker transitions are consistent under concurrent access; no data race, deadlock, unbounded task growth, or unhandled exception occurs.
- Recovery does not replay unbounded stale work or silently convert previously failed requests into successful responses.
- Test results record throughput and latency as measurements, not as a performance guarantee.

**Pass condition:** All configured bounds hold under the test workload and every response satisfies the mandatory commit invariant.

### AT-05 — Role separation and privileged deletion (TM-03)

**Setup**
- Configure separate service-writer, auditor/reader, and administrator identities where supported.
- Test against the real selected sink or its authorization layer; a mock-only test is insufficient for acceptance.

**Assertions**
- Writer credentials can perform only the approved write/append operation.
- Writer credentials cannot read, list, update, truncate, or delete historical events.
- Reader access is restricted to approved principals and operations.
- Administrative deletion or retention exceptions require explicit elevated credentials and follow the approved authorization workflow.
- Denied operations are recorded safely without exposing credentials or event contents.

**Pass condition:** Unauthorized operations are denied by the actual enforcement layer. If the selected sink cannot enforce the proposed separation, document the limitation and add a compensating control before acceptance.

### AT-06 — Integrity and tamper detection (TM-03)

**Setup**
- Modify, remove, reorder, or truncate test records using a privileged test fixture.
- Exercise any configured hash chain, signature/checkpoint, or immutable-storage feature.

**Assertions**
- The selected integrity mechanism detects the modifications it is designed to detect.
- Verification identifies the affected range or checkpoint without claiming to identify an actor unless separate evidence supports attribution.
- Administrative access and any authorized exception follow the approved workflow.

**Pass condition:** Documented tampering scenarios are detected and results are reproducible. Do not claim immutability or cryptographic integrity unless the mechanism is implemented and tested.

### AT-07 — Bounded shutdown and ambiguous commit (TM-02, TM-04)

**Setup**
- Terminate or restart the service while writes are pending; cancel clients during sink acknowledgement; induce a timeout after the sink may have committed.

**Assertions**
- Shutdown and cancellation complete within configured bounds.
- The service does not claim success without verified acknowledgement.
- Ambiguous commit state is handled according to the documented idempotency/reconciliation policy.
- No sensitive data is emitted through crash or shutdown diagnostics.

**Pass condition:** Behavior matches the documented delivery guarantee and all resources are released or bounded.

## 4. Required design decisions before coding

The following remain explicit blockers rather than assumptions:

1. The selected sink and exact durability acknowledgement.
2. Mandatory fail-closed scope and any permitted best-effort profile.
3. Queue capacity, request-size limit, concurrency limit, write deadline, and retry budget.
4. Circuit-breaker states, thresholds, recovery policy, and whether half-open probes are allowed.
5. Event identity, idempotency, duplicate handling, and ambiguous-timeout reconciliation.
6. Writer, reader, and administrator roles and actual storage enforcement capabilities.
7. Integrity mechanism, key management, immutable-storage requirements, and verification cadence.
8. Approved retention duration and deletion behavior across replicas, backups, exports, and legal holds.
9. Applicable legal and contractual obligations.

## 5. Evidence and release gate

- The document itself is not evidence that any runtime control or test exists.
- Test acceptance requires reproducible results against the exact commit and selected sink configuration.
- A green CI run alone does not establish durability, immutability, compliance, or production readiness.
- Keep audit pipeline implementation separate from PR #62; do not add upstream forwarding or authentication as incidental scope.
- **Checks are evidence. Release acceptance is a separate decision.**
