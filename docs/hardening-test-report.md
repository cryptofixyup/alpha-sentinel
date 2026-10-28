# Hardening PR test report

## Scope

Adds deterministic pre-trade execution gates and a post-signing settlement coordinator. Pre-trade controls cover kill switch, market evidence freshness, calibrated-probability declaration, net expected value, liquidity depth, slippage, daily loss, portfolio exposure, explicit MEV route policy, and idempotency identity. Settlement validates signed-payload binding, broadcast response, transaction hash, receipt chain, proposal/transaction digests, execution success, canonicality, and confirmation threshold.

## Automated test coverage

- `tests/test_execution_controls.py`: pass/reject cases for pre-trade gates and configured pipeline fail-closed behavior.
- `tests/test_settlement.py`: verified receipt success; signed-payload mismatch; rejected/ambiguous broadcast; verifier failure; malformed hash; wrong chain; mismatched proposal digest; reverted transaction; insufficient confirmations; non-canonical/reorg evidence.
- CI is authoritative for the PR head. Test files are not evidence of a passing run.

## Integration limits

`SettlementCoordinator` is a testable boundary over injected `SettlementGateway` and `ReceiptVerifier` implementations. It does not itself implement a chain RPC provider, private transaction relay, persistent broadcast idempotency, nonce reconciliation, replacement transaction logic, or finality polling. A broadcast timeout is marked `RECONCILIATION_REQUIRED`; callers must reconcile before any retry to avoid duplicate submission. A non-canonical receipt also requires reconciliation. Production adapter integration and target-chain tests remain required.

The pre-trade gate is injectable into `BoundaryPipeline`. For compatibility, the constructor still permits `execution_gate=None`; production must explicitly configure an `ExecutionGate` and provide authenticated, fresh evidence for every attempt.

## Remaining release blockers

- [ ] Production signer runs behind an isolated service/HSM/KMS boundary; orchestration, API, model, analytics and dashboard processes cannot access private keys.
- [ ] Chain-specific broadcaster/verifier integration tests on a fork or controlled testnet validate chain ID, tx hash, sender/recipient/nonce, receipt status, canonical block/hash, configured confirmations/finality, and reorg recovery.
- [ ] Durable idempotency and nonce reconciliation survive process crashes and ambiguous RPC timeouts.
- [ ] Atomic portfolio reservations across concurrent workers are verified.
- [ ] Production gate is mandatory in deployment configuration.
- [ ] Latest PR-head Python and JavaScript CI runs pass.

## Decision

**Release status: BLOCKED.** This report distinguishes unit-level adapter-boundary tests from real provider integration. No live-trading authorization is implied. Keep PR in draft until the listed blockers are resolved.
