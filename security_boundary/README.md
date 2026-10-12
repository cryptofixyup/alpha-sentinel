# Alpha Sentinel Transaction Security Boundary

This package establishes the transaction trust boundary before additional AI intelligence is introduced.

## Required order

`Risk → Policy → Proposal → Hash → Router-specific Transaction Builder → Simulation → Timelock/Approval → Isolated Signer → Broadcast → Verification`

## Security invariants

**Capability ≠ Authority.**

**Assertion ≠ Truth.** External or internal assertions are evidence inputs, not control-plane truth. Trust must be explicitly established from provenance, scope of authority, binding to the exact artifact, freshness, corroboration where required, and independent verification.

**The orchestration/LLM layer never receives wallet private-key material and never signs transactions.**

The signer receives only an exact transaction envelope cryptographically bound to an approved proposal digest.

## Fail-closed rules

- Risk rejection stops the pipeline.
- Policy rejection stops the pipeline.
- A missing router adapter stops the pipeline.
- A proposal/transaction digest mismatch stops the pipeline.
- Simulation failure stops the pipeline.
- Timelocked proposals cannot sign before expiry.
- The transaction is re-simulated after the timelock.
- The default signer is disabled.
- No private key is present in this package.
- Router calldata is never guessed or fabricated.

## Deliberate boundary

Broadcast and post-trade verification are outside the orchestration process. A production implementation must place them behind an explicit execution gateway and independently verify the resulting receipt and state transition.

## Router adapter requirement

Calldata must be `0x` followed by an even number of hexadecimal characters. This validation runs on every built or resumed transaction before simulation.

The repository does not yet contain enough router-specific information to safely implement a real transaction builder. A concrete adapter must supply the chain/router ABI, token addresses, route semantics, calldata encoding, value semantics, slippage handling, and deadline policy.

## Resuming a proposal

Pass a file-backed `ProposalStore(path)` as `proposal_store` to `BoundaryPipeline` for restart-safe operation. The default store is in memory and only survives retries within that pipeline instance. Use `execute(intent, exposure, request_id="unique-trade-id")` with the same ID to resume the immutable proposal and exact transaction. Changed intent or policy under that ID is rejected. Without an explicit ID, identical intent and policy reuse the same proposal; a distinct intended trade needs a new explicit ID.

The timelock derives its unlock time from the persisted proposal creation time. Large-trade deadlines cover the lock plus a 300-second signing window. Expired proposals cannot simulate or sign. Risk and policy checks are repeated on each attempt, and the persisted transaction is simulated again before approval. A signing attempt is claimed atomically before calling the signer; any retry after that claim requires external reconciliation, even if the signer failed. The store never records signed payloads or private keys. Its database and the system clock belong to the trusted local boundary.

## Authenticated daemon outcomes

Configure `AuthorizationDaemon` with distinct Ed25519 `executionPublicKey` and `verificationPublicKey` values. `execute({actor, evidence})` requires a gateway-signed execution result; `verify({actor, evidence})` requires an independently signed receipt for the same transaction hash. Missing keys or evidence fail closed, including direct terminal transitions through the lifecycle coordinator.

Each evidence object contains `kind` (`execution` or `receipt`), `status` (`EXECUTED` or `VERIFIED` respectively), `timestamp` in epoch milliseconds, `proposalId`, `proposalHash`, `transactionDigest`, `txHash`, and a base64url `signature`. `transactionDigest` is SHA-256 of the stable canonical bound transaction, exported by `security/transition-evidence.js`. Sign canonical bytes using `signingBytes` from `security/signed-result-verifier.js`; the signature field is excluded. Evidence must be no older than five minutes and cannot be future-dated. The independent receipt authority must actually check chain outcomes; this verifier authenticates its assertion and does not perform a live chain lookup or broadcast.
