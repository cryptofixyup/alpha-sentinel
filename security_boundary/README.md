# Alpha Sentinel Transaction Security Boundary

This package establishes the transaction trust boundary before additional AI intelligence is introduced.

## Required order

`Risk → Policy → Proposal → Hash → Router-specific Transaction Builder → Simulation → Timelock/Approval → Isolated Signer → Broadcast → Verification`

## Security invariant

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

The repository does not yet contain enough router-specific information to safely implement a real transaction builder. A concrete adapter must supply the chain/router ABI, token addresses, route semantics, calldata encoding, value semantics, slippage handling, and deadline policy.
