# Audit Sink Implementation Threat Model and Acceptance Criteria

**Status:** Design proposal; not implementation evidence  
**Scope:** Future audit-event emission and mandatory sink integration for the inspection-only guardrail proxy  
**Out of scope:** Upstream forwarding, caller authentication, authorization-policy changes, production-readiness claims, and changes to PR #62

## 1. Security objective

If audit events are configured as mandatory, a request must not receive a successful inspection response unless the corresponding audit event has reached the explicitly configured durability boundary. Failure to establish that boundary must fail closed with a generic service error. Audit handling must not disclose request content or secrets through any output path.

This document specifies acceptance criteria. It does not assert that runtime behavior exists.

## 2. Assets and security properties

- **Confidentiality:** request bodies, prompts, responses, credentials, tokens, arbitrary headers, and exception details never enter audit records or diagnostic output.
- **Integrity:** event fields are typed and allowlisted; callers cannot choose authoritative timestamps, request IDs, rule IDs, decisions, or outcome codes.
- **Completeness:** every request covered by mandatory audit mode has one well-defined audit outcome, including rejected requests and internal failures.
- **Ordering and binding:** the event is associated with the request and final decision it records; request IDs are generated server-side.
- **Availability:** bounded queues, write deadlines, and resource limits prevent sink failure from causing unbounded memory growth or indefinite request hangs.
- **Durability clarity:** enqueue, local buffer acceptance, sink acknowledgement, and durable commit are distinct states. Only the configured commit acknowledgement satisfies the mandatory profile.
- **Retention and access:** events expire according to approved policy and are accessible only to explicitly authorized roles.

## 3. Trust boundaries and data flow

1. Untrusted HTTP request enters the proxy.
2. Request-size and structural validation run before policy inspection.
3. Deterministic inspection computes the decision and allowlisted reason/rule codes.
4. A server-side event builder constructs the minimal typed event.
5. The configured audit sink commits the event and returns an acknowledgement with documented semantics.
6. Only after required acknowledgement may mandatory mode return a success response.
7. Diagnostics expose only bounded counters and health state, never request content or sink exception strings.

The request, its headers/body, client-supplied identifiers, rule text, sink error messages, and external storage are untrusted. The event builder, policy decision, and sink acknowledgement verification are security-critical components. Storage administrators and operators are privileged actors and must be covered by access controls and audit review.

## 4. Threats and required controls

| Threat | Required control |
| --- | --- |
| Prompt/body/secret leakage through logs, tracing, metrics, panic output, or sink errors | Typed allowlist; no raw request data; sanitize at construction; test every output channel with synthetic canaries |
| Client spoofs request ID, timestamp, decision, or reason | Server-generated request ID and timestamp; derive decision/reason from trusted policy result |
| Event forgery or field injection | Fixed schema and enums; reject unknown fields; escape/encode according to sink protocol; no caller-provided free-form reason |
| Success returned before durable commit | Mandatory mode waits for documented commit acknowledgement; enqueue-only acknowledgement is insufficient |
| Sink outage, timeout, full queue, or write rejection | Bounded resources and deadlines; generic 503; no success fallback; no stdout/stderr fallback |
| Ambiguous timeout where commit may have happened | Treat request outcome as failed/uncertain; stable event ID and sink idempotency where supported; document duplicate/reconciliation behavior |
| Duplicate or missing events during retry | Explicit idempotency key and retry policy; bounded retries; tests for at-least-once behavior and duplicate handling |
| Sink stalls or adversarially large input exhausts resources | Request-size limits, bounded queue, backpressure, per-write deadline, concurrency limits |
| Sensitive details leaked by exceptions | Map internal errors to fixed reason codes; never serialize exception text or stack traces |
| Unauthorized reading, alteration, or deletion | Least-privilege service identity, restricted operator roles, encryption in transit/at rest where supported, integrity controls and access review |
| Retention policy bypass through backups/rotation | Document lifecycle across primary storage, replicas, backups, exports, and rotated media; prove expiry behavior |
| Health endpoints reveal activity or event content | Aggregate counters only; access control where appropriate; no IDs, payloads, or per-request details |

## 5. Acceptance tests

All tests below are required before claiming implementation acceptance. Tests must run against the actual configured sink adapter, not only a mock. Mocks may be used for deterministic fault injection, but do not replace integration evidence.

### A. Schema and minimization

- Valid event serializes to the approved versioned schema and uses only documented fields and enums.
- Missing required fields, invalid enum values, unknown fields, and oversized metadata are rejected.
- Client-supplied request ID, timestamp, decision, rule ID, or reason cannot override server-derived values.
- Synthetic canaries placed in request body, headers, credentials, policy input, and sink exception text are absent from application logs, stdout, stderr, tracing, metrics, panic output, and persisted audit events.
- No raw body, body excerpt, token, credential, arbitrary header, exception string, stack trace, body hash, prompt fingerprint, or embedding is persisted.
- Rejected and internal-error outcomes use fixed reason codes and contain no free-form error detail.

### B. Mandatory commit semantics

- With a healthy sink, the response is not successful until the configured durability acknowledgement is received.
- A sink that acknowledges enqueue but not durable commit does not satisfy mandatory mode.
- Sink unavailable, write rejected, queue full, deadline exceeded, or invalid acknowledgement results in a generic 503 and no successful response.
- No sink failure path falls back to stdout, stderr, or a secondary unapproved store.
- If the client disconnects during commit, the service follows documented cancellation semantics and does not claim a known commit outcome where it is uncertain.
- A commit timeout after possible persistence is recorded as an uncertain outcome internally without exposing sink details; retry behavior cannot silently create unbounded duplicates.
- Retry/replay tests establish the documented delivery guarantee and idempotency behavior.

### C. Resource and resilience

- Queue size, request size, concurrent writes, retry count, and write deadline are bounded and configurable within validated limits.
- Under sustained sink failure, memory use remains bounded and requests fail within the configured deadline plus a documented response margin.
- Recovery after sink restoration does not replay unbounded stale work or return success for requests whose mandatory audit failed.
- Cancellation, shutdown, and restart behavior is documented and tested for in-flight writes.
- No deadlock or unbounded task growth occurs under repeated timeout and cancellation tests.

### D. Access, integrity, and retention

- Service credentials have write-only or otherwise minimal permissions required by the chosen sink design.
- Unauthorized reads, mutation, and deletion are denied by the sink or its access-control layer.
- Retention expiry is tested for primary data and every supported replica, backup, export, and rotation path.
- Operator access and policy exceptions are recorded without capturing event payloads.
- Integrity/tamper detection and restoration procedures are tested if claimed by the selected sink.

### E. Operational evidence

- CI runs unit, property/fuzz where applicable, integration, fault-injection, and secret-canary tests.
- Evidence identifies the exact commit SHA, sink implementation/configuration, test commands, test results, and relevant environment assumptions.
- Test reports do not contain secret canaries or sensitive request content.
- A green build alone does not establish production readiness or legal compliance.

## 6. Required design decisions before implementation

These decisions are blockers; do not silently choose them in code:

1. Is mandatory fail-closed audit mode the required profile, or is best-effort mode permitted for any endpoint?
2. What exact sink and acknowledgement constitute the durability boundary (database transaction commit, append-only service acknowledgement, or another defined contract)?
3. What are the maximum request size, queue capacity, write deadline, concurrency limit, and retry policy?
4. What is the idempotency key and how are ambiguous commit timeouts reconciled?
5. What retention period is approved, and how does it apply to replicas, backups, exports, and legal holds?
6. Which identities may write, read, administer, export, or delete events?
7. What encryption, integrity, replication, backup, deletion, and incident-response guarantees are required?
8. Which legal, contractual, and data-protection obligations apply to the deployment?

The previously suggested 30-calendar-day retention period is only a starting proposal, not an approved requirement or legal conclusion.

## 7. Rollout and acceptance gate

1. Approve the design decisions above and update the schema/policy documents.
2. Implement the event builder and sink adapter on a separate implementation branch.
3. Add tests before or alongside implementation; preserve fail-closed behavior.
4. Run integration and fault-injection tests against the actual sink.
5. Review the diff for data minimization and prohibited fallback paths.
6. Capture exact-SHA CI evidence and independent review.
7. Make a separate release-acceptance decision. Do not change PR #62's inspection-only scope or merge status as a side effect of this design work.

**Acceptance rule:** Checks are evidence. Release acceptance is a separate decision.
