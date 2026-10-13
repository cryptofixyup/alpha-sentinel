# Component Contracts

Status: architecture proposal.

## Scout — Discover

Produces observations, classifications and candidate evidence.

Must not authorize consequential actions.

## Trust Admission — Establish

Consumes identity, context and evidence and returns a scoped admission decision.

Must not treat connectivity or claimed identity as sufficient attestation.

## AEGIS — Observe

Produces continuous integrity/correlation evidence and may recommend restriction or quarantine.

AEGIS does not grant Alpha Sentinel authority and must not bypass deterministic policy.

## Sentinel — Decide

Owns deterministic consequence controls:

- policy
- exact-object binding
- simulation/isolation requirements
- approval/timelock
- execution authorization
- verification orchestration

## Evidence Chain — Prove

Preserves decision/evidence provenance and independent postcondition verification.

It must distinguish observed execution from verified outcome.

## Boundary Rule

Components exchange bounded evidence and decisions through explicit contracts.

No implicit trust is inherited merely because a component belongs to the Alpha Sentinel ecosystem.
