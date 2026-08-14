from dataclasses import replace

import pytest

from security_boundary.approval import Approval, Timelock, validate_approval
from security_boundary.execution import SignedTransaction
from security_boundary.models import Direction, ProposalStatus, TradeIntent, TransactionEnvelope
from security_boundary.pipeline import BoundaryPipeline
from security_boundary.policy import Policy
from security_boundary.risk import RiskEngine
from security_boundary.router import RouterAdapter, UnconfiguredRouterAdapter
from security_boundary.signer import DisabledSigner


WALLET = "0x1111111111111111111111111111111111111111"
ROUTER = "0x2222222222222222222222222222222222222222"


class FakeChain:
    def gas_price(self):
        return 20_000_000_000

    def estimate_gas(self, tx):
        return 100_000

    def call(self, tx):
        return None


class FailingSimulationChain(FakeChain):
    def estimate_gas(self, tx):
        raise RuntimeError("simulator unavailable")


class BlockingTimelock(Timelock):
    def ready(self, proposal_id, size_bps):
        return False


class FakeRouter(RouterAdapter):
    def __init__(self, mutate_digest=False):
        self.mutate_digest = mutate_digest

    def build(self, proposal):
        digest = "0" * 64 if self.mutate_digest else proposal.digest()
        return TransactionEnvelope(
            chain_id=proposal.chain_id,
            from_address=proposal.wallet,
            to_address=proposal.router,
            value=0,
            data="0x1234",
            gas_limit=150_000,
            gas_price_wei=20_000_000_000,
            nonce=1,
            proposal_digest=digest,
        )


class MalformedRouter(RouterAdapter):
    def build(self, proposal):
        return {"chain_id": proposal.chain_id, "data": "0x1234"}


def intent(size_bps=100):
    return TradeIntent(
        asset="ETH",
        direction=Direction.LONG,
        amount=1,
        size_bps=size_bps,
        reason="test recommendation",
        risk_score_bps=1000,
    )


def approval_provider(proposal, tx, simulation):
    return Approval.bind(proposal, tx, "test-approver", approved_at=1)


def make_pipeline(router, chain=None, timelock=None, approvals=None):
    return BoundaryPipeline(
        RiskEngine(),
        Policy(chain_id=1, wallet=WALLET, router=ROUTER),
        router,
        chain or FakeChain(),
        DisabledSigner(),
        timelock or Timelock(threshold_bps=500, duration_seconds=172800),
        approval_provider=approvals,
    )


def test_unconfigured_router_fails_closed():
    result = make_pipeline(UnconfiguredRouterAdapter()).execute(intent(), 0)
    assert result.status == ProposalStatus.FAILED
    assert "refusing to fabricate calldata" in result.reason
    assert result.signed_transaction is None


def test_malformed_transaction_envelope_fails_closed():
    result = make_pipeline(MalformedRouter()).execute(intent(), 0)
    assert result.status == ProposalStatus.FAILED
    assert "transaction build blocked" in result.reason
    assert result.signed_transaction is None


def test_proposal_transaction_digest_is_required():
    result = make_pipeline(FakeRouter(mutate_digest=True)).execute(intent(), 0)
    assert result.status == ProposalStatus.FAILED
    assert "transaction/proposal digest" in result.reason
    assert result.signed_transaction is None


def test_simulation_failure_blocks_signing():
    result = make_pipeline(FakeRouter(), chain=FailingSimulationChain()).execute(intent(), 0)
    assert result.status == ProposalStatus.SIMULATION_FAILED
    assert result.signed_transaction is None


def test_simulation_precedes_signing():
    result = make_pipeline(FakeRouter()).execute(intent(), 0)
    assert result.status == ProposalStatus.SIGNING_BLOCKED
    assert result.simulation is not None
    assert result.simulation.passed
    assert "approval provider" in result.reason
    assert result.signed_transaction is None


def test_position_limit_is_enforced():
    result = make_pipeline(FakeRouter()).execute(intent(size_bps=1600), 0)
    assert result.status == ProposalStatus.POLICY_REJECTED


def test_portfolio_exposure_limit_is_enforced():
    result = make_pipeline(FakeRouter()).execute(intent(), 5000)
    assert result.status == ProposalStatus.POLICY_REJECTED


def test_timelock_violation_fails_closed():
    result = make_pipeline(
        FakeRouter(),
        timelock=BlockingTimelock(threshold_bps=500, duration_seconds=172800),
    ).execute(intent(size_bps=600), 0)
    assert result.status == ProposalStatus.TIMELOCKED
    assert result.signed_transaction is None


def test_large_trade_enters_timelock():
    result = make_pipeline(FakeRouter()).execute(intent(size_bps=600), 0)
    assert result.status == ProposalStatus.TIMELOCKED
    assert result.proposal is not None


def test_approval_must_bind_to_exact_transaction():
    captured = {}

    def bad_approval(proposal, tx, simulation):
        captured["tx"] = tx
        valid = Approval.bind(proposal, tx, "test-approver", approved_at=1)
        return replace(valid, transaction_digest="0" * 64)

    result = make_pipeline(FakeRouter(), approvals=bad_approval).execute(intent(), 0)
    assert result.status == ProposalStatus.SIGNING_BLOCKED
    assert "exact transaction envelope" in result.reason
    assert result.signed_transaction is None
    assert captured["tx"].digest() != "0" * 64


def test_approval_binds_proposal_and_transaction():
    captured = {}

    def good_approval(proposal, tx, simulation):
        approval = Approval.bind(proposal, tx, "test-approver", approved_at=1)
        captured["approval"] = approval
        return approval

    result = make_pipeline(FakeRouter(), approvals=good_approval).execute(intent(), 0)
    assert result.status == ProposalStatus.SIGNING_BLOCKED
    assert "signing disabled" in result.reason
    assert captured["approval"].proposal_digest == result.proposal.digest()
    assert captured["approval"].transaction_digest == result.transaction.digest()


def test_validate_approval_rejects_proposal_mismatch():
    result = make_pipeline(FakeRouter()).execute(intent(), 0)
    proposal = result.proposal
    tx = result.transaction
    assert proposal is not None and tx is not None
    approval = Approval.bind(proposal, tx, "test-approver", approved_at=1)
    other = replace(approval, proposal_digest="0" * 64)
    with pytest.raises(PermissionError, match="not bound to proposal"):
        validate_approval(proposal, tx, other)


def test_broadcast_without_authorized_signed_envelope_is_rejected():
    result = make_pipeline(FakeRouter()).execute(intent(), 0)
    proposal = result.proposal
    tx = result.transaction
    assert proposal is not None and tx is not None
    forged = SignedTransaction(
        raw="0xf00d",
        proposal_digest=proposal.digest(),
        transaction_digest="0" * 64,
    )
    with pytest.raises(ValueError, match="exact transaction"):
        forged.validate(proposal, tx)


def test_no_private_key_is_required_by_boundary():
    source = open("security_boundary/signer.py", encoding="utf-8").read()
    assert "PRIVATE_KEY" not in source
    assert "WALLET_PRIVATE_KEY" not in source
