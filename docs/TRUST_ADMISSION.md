# Trust Admission

Status: specification draft; not implemented.

Trust Admission answers:

**Under what bounded conditions may an untrusted external capability become consequential?**

## AdmissionRequest

Conceptual fields:

- artifact
- artifact_type
- claimed_identity
- observed_identity
- origin
- requested_capabilities
- evidence[]
- attestations[]
- risk_signals[]
- policy_context
- isolation_requirements
- expiry

## AdmissionDecision

A decision is one of:

- DENY
- QUARANTINE
- RESTRICT
- ADMIT

It binds:

- permitted_capabilities[]
- prohibited_capabilities[]
- evidence_hash
- policy_version
- decision_hash
- expires_at

ADMIT is never equivalent to permanent trust.

## Applications

**Substrate Validation** applies Trust Admission to chains, RPC endpoints, L2s, bridges and protocol endpoints.

**Clean-Room Execution / Sandboxed Hiring Rails** applies Trust Admission plus isolation to repositories, packages, coding exercises and executable artifacts.

These are applications of one primitive, not independent authorization systems.

## Failure Behavior

Missing identity, stale attestation, conflicting evidence, unknown policy context, expired admission, or failed re-attestation must not silently upgrade authority.

Consequential operations fail closed unless explicit policy defines a narrower safe behavior.
