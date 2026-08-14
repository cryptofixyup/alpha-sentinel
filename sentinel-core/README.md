# Alpha Sentinel Core

This directory is the isolated security-critical core boundary.

## Design invariant

Autonomous components may reason, construct, route, and submit proposals, but they do not possess authority to mutate security-critical state or create authorization authority.

All lifecycle transitions must be accepted or rejected by a deterministic validator operating over durable state.

## Initial boundaries

- `proposals/` — untrusted requests for state transitions.
- `policy/` — deterministic authorization and transition policy.
- `state/` — durable security-critical state model.
- `lifecycle/` — explicit transition machinery.
- `router/` — adapter boundary; no implicit authorization.
- `tests/` — invariant and transition tests.

No signer, private-key material, production broadcaster, or external transaction authority belongs in this initial skeleton.
