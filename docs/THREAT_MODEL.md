# Threat Model — Human Intent to Consequence

Status: architecture threat-model draft.

Protected path:

human intent -> input/artifact -> identity/substrate -> session -> capability -> policy -> authorization -> execution -> postcondition

## Threat Classes

- identity/substrate impersonation
- malicious but functional endpoints
- compromised or spoofed sessions
- valid credentials used outside intended context
- capability escalation
- stale admission after environment change
- mutable artifact after approval
- confused-deputy/module authorization failure
- malicious repository/package/executable code
- AI/tool proposal attempting to become authority
- policy bypass or policy-version drift
- simulation/approval mismatch
- signer or execution-path substitution
- false success reporting
- evidence tampering, omission or provenance loss

## Required Controls

Identity/attestation, scoped capability grants, deterministic policy, exact-artifact binding, isolation, simulation where applicable, approval/timelock where applicable, independent verification, re-attestation and append-only/auditable evidence.

This document defines threat classes, not claims that all controls are implemented on main.
