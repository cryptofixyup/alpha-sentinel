# Frankenstein Authorized Agent — isolated integration review

Status: **experimental / not approved for production**.

## Provenance
Source artifact: `full_frankenstein_agent.optimized.py` uploaded in the associated engineering conversation. This branch includes the reviewed reference implementation: `frankenstein_agent.py`, `authority.py`, `issue_grant.py`, and `tests/test_authority.py`. Their presence establishes integration into this experimental branch only; it is not evidence of production approval or end-to-end verification.

## Existing repository contract
The existing `security_boundary/` transaction pipeline owns risk, policy, proposal binding, simulation, approval, isolated signing, and post-signing separation. The Frankenstein RAG agent must not bypass, replace, or mutate this pipeline.

## Intended placement
`experiments/frankenstein-authorized/` — independent Python RAG experiment. Keep all dependencies, caches, databases, secrets, and tests isolated from the root project.

## Review gates before code import
1. Verify source package provenance and exact file hashes.
2. Confirm no credentials, Chroma databases, generated model weights, or user corpora are committed.
3. Preserve hybrid dense/BM25 retrieval and local read-only book search.
4. Deny external web search by default. Exact-query grants must be issued only by a trusted control plane.
5. Require tamper, expiry, revocation, concurrent replay, restart, and crash/uncertainty tests.
6. Document that HMAC shared-secret grants are local prototypes, not interoperable signatures.
7. Validate Python dependency compatibility and end-to-end retrieval separately from mock authorization tests.
8. Do not connect this agent to transaction signing, broadcast, or wallet keys.
9. Obtain CI evidence on the exact PR head before requesting merge.

## Known design limitations
Atomic grant reservation is not exactly-once external effect execution. Tool-returned strings are not independent outcome evidence. A reserved grant whose process crashes requires reconciliation. A signed grant alone does not prove operator identity or policy correctness.

This experimental integration does not modify the production authorization pipeline. It adds the isolated `.github/workflows/frankenstein-authorized-regression.yml` workflow for mock-based authority regression testing.
