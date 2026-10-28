# Hardening PR test report

## Scope

Adds deterministic pre-trade execution gates, atomic exposure reservations, a durable broadcast journal, and a post-signing settlement coordinator. Pre-trade controls cover kill switch, market evidence freshness, calibrated-probability declaration, net expected value, liquidity depth, slippage, daily loss, portfolio exposure, explicit MEV route policy, and idempotency identity.

## Automated test coverage

- `tests/test_execution_controls.py`: pass/reject cases for pre-trade gates, including production durability requirements.
- `tests/test_execution_state.py`: atomic reservations, cross-connection contention, identity reuse rejection, reservation reconciliation, durable broadcast claims, and production in-memory storage rejection.
- `tests/test_security_boundary.py`: existing authorization controls plus an integration test proving a second pipeline cannot sign when atomic exposure capacity is exhausted.
- `tests/test_settlement.py`: receipt success/failure, durable no-resubmit behavior after ambiguous broadcast, journal replay, reorg handling, and reservation retention/commit.
- CI is authoritative for the exact PR head. Tests present in source are not evidence of a passing run.

## Implemented controls and boundaries

- `SQLiteExecutionState` serializes reservations with `BEGIN IMMEDIATE`, stores reservation and broadcast states durably, rejects idempotency-key reuse with a different payload, and does not permit automatic rebroadcast after an unresolved claim.
- `BoundaryPipeline` reserves portfolio capacity before signing when an execution-state store is configured. Production construction now requires an explicit `ExecutionGate`, persistent execution-state storage, and persistent proposal storage.
- `SettlementCoordinator` requires an execution-state store, persists the claim before the first broadcast, reuses known transaction hashes rather than resubmitting, rechecks receipt evidence on repeated calls, and commits exposure only after verified confirmation.
- Ambiguous, malformed, or non-canonical outcomes retain exposure and require reconciliation rather than freeing capacity.

## Integration limits — still release blocking

- SQLite reservation safety applies only when every worker shares the same database file on a filesystem with correct SQLite locking semantics. Multi-host deployments require a shared transactional database adapter with equivalent locking and uniqueness guarantees; that adapter has not been implemented or tested here.
- `SettlementGateway` and `ReceiptVerifier` remain injected interfaces. There is no production chain RPC/private-relay implementation, nonce reconciliation, replacement-transaction workflow, or finality polling in this repository change. The target provider and operational routing policy must be selected and tested against the target chain before live execution.
- A broadcast timeout is marked `RECONCILIATION_REQUIRED`; no automatic retry occurs. A deployment reconciliation worker must query the provider by transaction hash/nonce/idempotency identity and explicitly record the result before another attempt.
- The isolated signer is still an interface plus a disabled default. HSM/KMS custody, signer-service authentication, network isolation, policy enforcement at the signer, and independent access-control evidence must be deployed and audited.
- Production configuration must set `ALPHA_SENTINEL_ENV=production`, inject the gate and durable stores, provide authenticated fresh market evidence on every attempt, and use the same execution-state database for pipeline reservations and settlement.

## Remaining release blockers

- [ ] Independent CI success on the latest PR head after the execution-state, pipeline, and settlement changes.
- [ ] Shared transactional database adapter selected and verified for the actual worker topology (SQLite is not a multi-host coordination service).
- [ ] Chain-specific broadcaster/verifier, nonce recovery, timeout reconciliation, replacement policy, confirmation/finality polling, and reorg tests on a fork or controlled testnet.
- [ ] Production signer service/HSM/KMS isolation and least-privilege verification.
- [ ] Production deployment configuration and operational reconciliation runbook reviewed against the actual environment.

## Decision

**Release status: BLOCKED.** The code now contains durable single-database reservation and broadcast-journal mechanisms, but those are not substitutes for the actual multi-worker database, provider, signer, and deployment integrations. No merge or live-trading authorization is implied. Keep PR in draft until every release blocker has independent evidence.
