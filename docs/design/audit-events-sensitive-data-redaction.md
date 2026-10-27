# Design Specification: Audit Events and Sensitive-Data Redaction

**Status:** Draft — design only  
**Scope:** Audit event schema and data-minimization/redaction contract  
**Related prototype:** `guardrail-proxy/` on PR #62  
**Boundary:** This document does not authorize adding audit logging, disk writes, stdout/stderr logging, or upstream forwarding to PR #62.

## 1. Goals and non-goals

### Goals
- Emit a consistent, versioned record of an inspection decision without recording the inspected content.
- Make event fields allowlisted and typed; prohibit free-form request-derived values.
- Prevent raw prompts, request/response bodies, credentials, tokens, and secrets from entering any log sink.
- Define testable acceptance criteria before implementation.

### Non-goals
- Implementing a log sink or changing the current inspection-only service.
- Capturing prompt excerpts, body hashes, embeddings, or other content fingerprints.
- Defining upstream forwarding.
- Claiming compliance, tamper-proofing, or production readiness.

## 2. Event schema

The proposed wire format is one JSON object per event (JSON Lines if a future sink selects that framing). The object contains metadata only.

### Required fields

| Field | Type / constraint | Meaning |
|---|---|---|
| `schema_version` | String enum; initially `"1"` | Explicit schema version. |
| `event_type` | Enum; initially `"inspection_decision"` | Stable event category. |
| `request_id` | Server-generated UUIDv4 | Correlates a request across internal stages. Never trust a caller-supplied value as the canonical ID. |
| `timestamp` | RFC 3339 UTC timestamp, e.g. `2026-10-27T21:00:00Z` | Server observation time; not a claim about client time. |
| `decision` | Enum: `allow`, `reject`, `error` | Policy decision at the inspection boundary. |
| `rule_id` | Stable allowlisted identifier or `null` | Rule identifier only, never the matched signature or request text. |
| `outcome` | Enum: `inspection_allowed`, `policy_rejected`, `invalid_request`, `request_too_large`, `timed_out`, `internal_error` | Machine-readable terminal outcome. |
| `reason_code` | Stable allowlisted code or `null` | Coarse explanation; never a raw error message. |
| `duration_ms` | Integer, 0–300000 | Server-measured duration, capped for schema safety. |
| `payload_bytes` | Integer, 0–67108864 | Request body byte count only; no body content. Values outside configured service limits should be represented by the observed bounded count or a documented saturation value. |
| `service_version` | Bounded build/version identifier | Build provenance; must not contain environment variables, paths, or secrets. |

Unknown fields MUST be rejected by schema validation or omitted by the event builder. New fields require a schema-versioning decision and security review.

### Illustrative event

This is a schema example, not a record emitted by the current prototype:

```json
{
  "schema_version": "1",
  "event_type": "inspection_decision",
  "request_id": "6b6b8b1e-1f5b-4c86-a3b8-30c38d8b4e44",
  "timestamp": "2026-10-27T21:00:00Z",
  "decision": "reject",
  "rule_id": "SIG_PROMPT_OVERRIDE_001",
  "outcome": "policy_rejected",
  "reason_code": "SIGNATURE_MATCH",
  "duration_ms": 2,
  "payload_bytes": 184,
  "service_version": "0.1.0"
}
```

### Decision and outcome consistency

- `allow` MUST pair with `inspection_allowed`.
- `reject` MUST pair with `policy_rejected`, `invalid_request`, or `request_too_large`.
- `error` MUST pair with `timed_out` or `internal_error`.
- `rule_id` is non-null only when a stable configured rule actually matched. Validation failures and internal errors use `null`.
- `reason_code` values are drawn from a fixed enum (initially `SIGNATURE_MATCH`, `MALFORMED_REQUEST`, `BODY_LIMIT_EXCEEDED`, `DEADLINE_EXCEEDED`, `INSPECTION_FAILURE`). Do not include exception text or user input in the code.

## 3. Sensitive-data redaction and minimization contract

The primary control is **never collect sensitive content**, not “log it and redact it later.”

### Prohibited from all logs and telemetry

- Raw prompts, request/response bodies, body excerpts, or tool-call arguments.
- Authorization headers, cookies, API keys, bearer tokens, passwords, private keys, session identifiers, and other credentials.
- Environment-variable values, connection strings, full URLs containing query strings or credentials, and filesystem paths that may reveal secrets.
- Raw exception/panic messages, stack traces, request headers, caller-supplied IDs, or arbitrary caller-controlled strings.
- Body hashes, prompt fingerprints, embeddings, or reversible/low-entropy content-derived identifiers. These can leak information and are not required for this schema.

The prohibition applies to stdout, stderr, application logs, tracing spans, metrics labels, crash reports, panic hooks, and test failure output—not only the future audit sink.

### Required implementation pattern

1. Build audit records from typed, allowlisted fields; do not serialize request structs or headers.
2. Generate `request_id` inside the service. If client correlation is later required, define a separate validated field and threat model; do not replace the canonical ID.
3. Map internal errors to fixed `reason_code` values. Never place `error.to_string()`, debug formatting, panic payloads, or arbitrary strings in an event.
4. Keep rule identifiers static and reviewed. Log the rule ID, not its signature, regex, matched bytes, or detector excerpt.
5. Do not use post-hoc regex redaction as the primary safeguard. It is incomplete for unknown secrets and prompt content.
6. If a future sink or library emits its own diagnostics, configure it not to include payloads or credentials and test that behavior. Do not assume application-level redaction covers dependency logs.
7. Do not include high-cardinality or caller-controlled values in metrics labels.

## 4. Failure behavior and retention: decisions required before implementation

This specification intentionally does not select a storage sink or retention duration. Those choices require a separate decision record covering:

- **Sink failure:** whether audit durability is required before returning a decision; queue bounds; backpressure; timeout; behavior on full queue/disk; and how to avoid recursive logging of sink failure. No sensitive fallback to stdout/stderr is permitted. The selected policy must be explicit and tested.
- **Availability vs. audit completeness:** if the service continues when logging fails, the event gap must be observable through a separate non-sensitive health signal. If it fails closed, the failure response must not leak internal details. Product/security owners must choose the required mode.
- **Storage and access:** sink location, encryption at rest and in transit where applicable, least-privilege reader/writer roles, rotation, integrity controls, and backup behavior.
- **Retention and deletion:** an explicit duration based on operational need and applicable obligations; automatic expiry; deletion from rotations and backups; and documented access/audit of log reads. Do not retain indefinitely by default.
- **Clock and ordering:** UTC timestamps are for event time; they do not guarantee total ordering. Add a sequence mechanism only if a concrete consumer requires it.

Until those decisions are approved, implementation MUST NOT choose an implicit fallback sink or retention policy.

## 5. Acceptance criteria

The design is ready for implementation review only when all of the following are testable:

- [ ] Schema validates required fields, enums, ranges, nullability, and decision/outcome consistency.
- [ ] Unknown fields and free-form strings cannot enter events through the normal event-builder API.
- [ ] Canary values placed in request bodies and headers (e.g. fake API keys, bearer tokens, passwords, and unique prompt markers) do not appear in captured stdout, stderr, tracing, panic output, audit output, or test diagnostics.
- [ ] No request body, excerpt, body hash, prompt fingerprint, or matched-content bytes are emitted.
- [ ] Error paths produce only fixed reason codes, not raw error strings or stack traces.
- [ ] Oversize, malformed, timeout, concurrent-request, and detector-match paths satisfy the same redaction rules.
- [ ] Sink failure, retention, access control, rotation, and deletion behavior are separately specified and tested before a persistent sink is enabled.
- [ ] Tests use synthetic secrets only; no production prompts or real credentials.

## 6. Scope and release gate

PR #62 remains inspection-only. This document is a proposed contract, not evidence that logging exists or that redaction has been tested. Any implementation should be a separate change with its own tests and review. Upstream forwarding remains out of scope and requires a separate threat model and acceptance gate.
