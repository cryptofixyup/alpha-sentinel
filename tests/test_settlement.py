from dataclasses import replace

import pytest

from security_boundary.execution import BroadcastResult, SignedTransaction
from security_boundary.execution_state import SQLiteExecutionState
from security_boundary.models import Direction, TradeIntent, TradeProposal, TransactionEnvelope
from security_boundary.settlement import (
    ReceiptEvidence, SettlementCoordinator,
)


TX_HASH = "0x" + "a" * 64


def objects():
    proposal = TradeProposal(
        proposal_id="proposal-1", created_at=100, chain_id=1,
        wallet="0x1111111111111111111111111111111111111111",
        router="0x2222222222222222222222222222222222222222",
        asset="ETH", direction=Direction.LONG, amount=1, size_bps=100,
        max_slippage_bps=100, gas_price_limit_wei=20_000_000_000,
        deadline=1000, policy_version="v1", reason="test", risk_score_bps=100,
    )
    tx = TransactionEnvelope(
        chain_id=1, from_address=proposal.wallet, to_address=proposal.router,
        value=0, data="0x1234", gas_limit=150000,
        gas_price_wei=20_000_000_000, nonce=7,
        proposal_digest=proposal.digest(),
    )
    signed = SignedTransaction("opaque-signed-payload", proposal.digest(), tx.digest())
    return proposal, tx, signed


class Gateway:
    def __init__(self, result=None, error=None):
        self.result = result or BroadcastResult(TX_HASH, True, "")
        self.error = error
        self.calls = 0

    def broadcast(self, signed, proposal, tx):
        self.calls += 1
        if self.error:
            raise self.error
        signed.validate(proposal, tx)
        return self.result


class Verifier:
    def __init__(self, receipt=None, error=None):
        self.receipt = receipt
        self.error = error
        self.calls = 0

    def verify_receipt(self, proposal, tx, tx_hash):
        self.calls += 1
        if self.error:
            raise self.error
        if self.receipt:
            return self.receipt
        return ReceiptEvidence(
            tx_hash=tx_hash, chain_id=proposal.chain_id,
            proposal_digest=proposal.digest(), transaction_digest=tx.digest(),
            success=True, confirmations=12, required_confirmations=12,
            canonical=True,
        )


def test_verified_canonical_receipt_confirms():
    proposal, tx, signed = objects()
    gateway, verifier = Gateway(), Verifier()
    result = SettlementCoordinator(gateway, verifier, SQLiteExecutionState(":memory:")).settle(signed, proposal, tx)
    assert result.status == "CONFIRMED"
    assert result.tx_hash == TX_HASH
    assert gateway.calls == verifier.calls == 1


def test_invalid_signed_binding_never_broadcasts():
    proposal, tx, signed = objects()
    gateway, verifier = Gateway(), Verifier()
    result = SettlementCoordinator(gateway, verifier).settle(
        replace(signed, transaction_digest="bad"), proposal, tx
    )
    assert result.status == "FAILED"
    assert gateway.calls == verifier.calls == 0


def test_ambiguous_broadcast_requires_reconciliation_not_retry():
    proposal, tx, signed = objects()
    gateway, verifier = Gateway(error=TimeoutError("timeout after submit")), Verifier()
    result = SettlementCoordinator(gateway, verifier).settle(signed, proposal, tx)
    assert result.status == "RECONCILIATION_REQUIRED"
    assert verifier.calls == 0


def test_rejected_broadcast_never_verifies_receipt():
    proposal, tx, signed = objects()
    gateway = Gateway(BroadcastResult(TX_HASH, False, "nonce too low"))
    verifier = Verifier()
    result = SettlementCoordinator(gateway, verifier).settle(signed, proposal, tx)
    assert result.status == "FAILED"
    assert verifier.calls == 0


@pytest.mark.parametrize("receipt,expected,reason", [
    (lambda p,t: ReceiptEvidence(TX_HASH, 2, p.digest(), t.digest(), True, 12, 12, True), "FAILED", "chain mismatch"),
    (lambda p,t: ReceiptEvidence(TX_HASH, 1, "bad", t.digest(), True, 12, 12, True), "FAILED", "does not bind"),
    (lambda p,t: ReceiptEvidence(TX_HASH, 1, p.digest(), t.digest(), False, 12, 12, True), "FAILED", "reverted"),
    (lambda p,t: ReceiptEvidence(TX_HASH, 1, p.digest(), t.digest(), True, 2, 12, True), "BROADCAST", "awaiting"),
    (lambda p,t: ReceiptEvidence(TX_HASH, 1, p.digest(), t.digest(), True, 12, 12, False), "RECONCILIATION_REQUIRED", "non-canonical"),
])
def test_receipt_conditions_fail_closed_or_wait(receipt, expected, reason):
    proposal, tx, signed = objects()
    result = SettlementCoordinator(Gateway(), Verifier(receipt(proposal, tx)), SQLiteExecutionState(":memory:")).settle(signed, proposal, tx)
    assert result.status == expected
    assert reason in result.reason


def test_verifier_failure_does_not_report_success():
    proposal, tx, signed = objects()
    result = SettlementCoordinator(Gateway(), Verifier(error=TimeoutError("RPC down"))).settle(signed, proposal, tx)
    assert result.status == "RECONCILIATION_REQUIRED"


def test_malformed_transaction_hash_rejected():
    proposal, tx, signed = objects()
    result = SettlementCoordinator(
        Gateway(BroadcastResult("0x123", True, "")), Verifier()
    ).settle(signed, proposal, tx)
    assert result.status == "FAILED"
    assert "invalid transaction hash" in result.reason
