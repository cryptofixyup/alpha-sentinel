# Capability is not authority

An LLM or agent may discover, reason, coordinate and propose. These capabilities do not grant authority to approve, sign, broadcast, alter policy or advance the lifecycle.

## Boundary contract

Principal identity and classification must come from a trusted authentication boundary. Prompts, retrieved content, tool results and model-generated role labels are untrusted. An agent must not choose its own `actor.kind` or impersonate an operator identifier.

`Policy.authorize` rejects object principals classified as `agent` or `model` before consulting its authorization callback, including when that callback is permissive. Trusted operator objects and legacy string actors remain subject to the callback. Proposal intake stays separate from authorization.

Current main's canonical lifecycle is `PROPOSED → AUTHORIZED → VALIDATED → BOUND → SIMULATED → TIMED_WAIT → RE_SIMULATED → APPROVED → EXECUTED → VERIFIED`. Approval follows binding and final simulation. Terminal states require authenticated execution and independent receipt evidence bound to the exact proposal and transaction. The Python boundary similarly binds approval to the immutable proposal and exact re-simulated envelope, checks expiry, and delegates signing to an isolated interface whose default implementation is disabled.

## Evidence and limits

Regression tests demonstrate that known agent/model principals are rejected without invoking the callback or changing durable lifecycle state. They also preserve callback enforcement for trusted object and legacy string actors.

This check trusts caller-supplied classification and does not authenticate identity. A caller who can forge `actor.kind`, use a legacy string or invoke lower-level components is outside this check's demonstrated protection. Production operation requires a trusted authenticated ingress, independently enforced signer policy, and a gateway that verifies real chain outcomes. This change does not establish those components or certify live execution.
