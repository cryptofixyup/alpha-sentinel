import pytest

from security_boundary.approval import Timelock
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


def intent(size_bps=100):
    return TradeIntent(
        asset="ETH",
        direction=Direction.LONG,
        amount=1,
        size_bps=size_bps,
        reason="test recommendation",
        risk_score_bps=1000,
    )


def make_pipeline(router):
    return BoundaryPipeline(
        RiskEngine(),
        Policy(chain_id=1, wallet=WALLET, router=ROUTER),
        router,
        FakeChain(),
        DisabledSigner(),
        Timelock(threshold_bps=500, duration_seconds=172800),
    )


def test_unconfigured_router_fails_closed():
    result = make_pipeline(UnconfiguredRouterAdapter()).execute(intent(), 0)
    assert result.status == ProposalStatus.FAILED
    assert "refusing to fabricate calldata" in result.reason
    assert result.signed_transaction is None


def test_proposal_transaction_digest_is_required():
    result = make_pipeline(FakeRouter(mutate_digest=True)).execute(intent(), 0)
    assert result.status == ProposalStatus.FAILED
    assert "digest mismatch" in result.reason
    assert result.signed_transaction is None


def test_simulation_precedes_signing():
    result = make_pipeline(FakeRouter()).execute(intent(), 0)
    assert result.status == ProposalStatus.SIGNING_BLOCKED
    assert result.simulation is not None
    assert result.simulation.passed
    assert result.signed_transaction is None


def test_position_limit_is_enforced():
    result = make_pipeline(FakeRouter()).execute(intent(size_bps=1600), 0)
    assert result.status == ProposalStatus.SIGNING_BLOCKED


def test_portfolio_exposure_limit_is_enforced():
    result = make_pipeline(FakeRouter()).execute(intent(), 5000)
    assert result.status == ProposalStatus.POLICY_REJECTED


def test_large_trade_enters_timelock():
    result = make_pipeline(FakeRouter()).execute(intent(size_bps=600), 0)
    assert result.status == ProposalStatus.TIMELOCKED
    assert result.proposal is not None


def test_no_private_key_is_required_by_boundary():
    source = open("security_boundary/signer.py", encoding="utf-8").read()
    assert "PRIVATE_KEY" not in source
    assert "WALLET_PRIVATE_KEY" not in source
