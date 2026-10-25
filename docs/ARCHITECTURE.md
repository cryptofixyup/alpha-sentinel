# Alpha Sentinel Architecture vNext

Status: architecture proposal. This document does not claim implementation.

## North Star

Alpha Sentinel is a trust-admission and deterministic-authority ecosystem for interacting with untrusted digital systems.

Inputs may be unknown or hostile. Intelligence may inspect and propose. Evidence establishes context. Deterministic controls decide whether capability becomes authority. Isolation limits consequence. Cryptography binds decisions to artifacts. Independent verification determines what actually occurred.

## System Model

Discover -> Establish -> Observe -> Decide -> Prove

1. **Scout / Discovery** collects signals and evidence. Discovery grants no authority.
2. **Trust Admission / Establish** identifies, attests and scopes an external capability before consequential access.
3. **AEGIS / Observe** contributes continuous session-integrity and correlation evidence. AEGIS is not an authorization authority.
4. **Sentinel / Decide** applies deterministic policy, binding, simulation, approval/timelock and isolated execution controls.
5. **Evidence Chain / Prove** records decisions and independently verifies postconditions.

## Universal Path

UNTRUSTED INPUT
-> NORMALIZE
-> CLASSIFY
-> IDENTIFY
-> ATTEST
-> ASSESS
-> POLICY
-> ISOLATE / SIMULATE
-> AUTHORIZE or DENY
-> EXECUTE
-> VERIFY
-> RE-ATTEST

Supported input classes may include URLs, repositories, files, transactions, wallet requests, contracts, RPC endpoints, chains/L2s, bridges, APIs, webhooks, sessions, packages, executable code and AI tools.

New input classes must enter through the same authority model.

## Continuous Trust

Admission is scoped and expiring:

ADMIT -> OPERATE -> OBSERVE -> RE-ATTEST -> CONTINUE | RESTRICT | QUARANTINE | REVOKE

## AI Boundary

AI may discover, classify, correlate, explain, recommend and generate candidate policy/actions.

AI must not independently grant authority, weaken policy, approve its own proposal, expand its capabilities, bypass isolation, or declare its own execution verified.

## Implementation Caveat

The current main-branch lifecycle is an earlier implementation and must not be described as implementing this vNext architecture.

Existing open PRs and lifecycle work remain separate evidence streams.

This documentation branch changes no runtime behavior.
