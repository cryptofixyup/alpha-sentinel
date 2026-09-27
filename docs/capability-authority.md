# Capability is not authority

Status: design rule and local regression check; deployment enforcement is not demonstrated.

An LLM or agent may discover, reason, coordinate, and propose. None of those capabilities grants permission to approve, sign, broadcast, alter policy, or change lifecycle state. The deterministic policy boundary must decide each privileged transition using a principal established outside model-controlled text. A simulation result is evidence about a transaction, not an approval or credential.

## Boundary contract

1. Treat prompts, retrieved content, tool results, agent messages, and model-generated role labels as untrusted proposals or evidence.
2. Obtain principal identity and permissions from a trusted authentication boundary. Do not let an agent supply or rewrite its own `actor.kind` or impersonate an operator identifier.
3. Deny principals classified as `agent` or `model` at `Policy.authorize`, even when a permissive callback would otherwise allow them. Keep proposal intake separate from authorization.
4. Check the exact proposal and transaction identity at each transition. Approval must bind to the exact successful simulation and transaction before signing; a change invalidates approval.
5. An isolated signer must independently verify the approved binding and policy decision. Logging, monitoring, and prompt instructions do not replace this gate.

## Evidence and limits

The local `Policy` check rejects object principals with `kind: agent` or `kind: model`; the regression test also checks that the lifecycle does not advance. The current code still accepts legacy string actors and trusts the caller's principal classification. It does not establish authenticated identity, signer isolation, or approval bound to a later simulation. Those require separate implementation and tests before any end-to-end security claim. In particular, this repository's current lifecycle places approval before binding and simulation; that ordering must be corrected before claiming approval of an exact simulated transaction.

Security evaluation should test capability, authority, containment, and consequences separately. Successful agent coordination or exploitation does not imply personhood; conventional software loops do not imply harmless behavior.
