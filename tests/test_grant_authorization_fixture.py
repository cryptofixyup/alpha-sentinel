"""Bounded authorization integration fixture: no private keys or network access.

This exercises the Python authorization boundary through signing with an
in-memory test double. It does NOT establish process-isolated signing,
broadcast, or on-chain receipt verification.
"""
from dataclasses import replace

from security_boundary.approval import Approval, Timelock
from security_boundary.execution import SignedTransaction
from security_boundary.models import Direction, ProposalStatus, TradeIntent, TransactionEnvelope
from security_boundary.pipeline import BoundaryPipeline
from security_boundary.policy import Policy
from security_boundary.risk import RiskEngine
from security_boundary.router import RouterAdapter
from security_boundary.signer import DisabledSigner
from security_boundary.store import ProposalStore

WALLET = "0x1111111111111111111111111111111111111111"
ROUTER = "0x2222222222222222222222222222222222222222"


class DeterministicChain:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    def gas_price(self):
        return 20_000_000_000

    def estimate_gas(self, tx):
        self.calls += 1
        if self.fail:
            raise RuntimeError("simulator offline")
        return 100_000

    def call(self, tx):
        self.calls += 1
        if self.fail:
            raise RuntimeError("eth_call failed")


class FixedRouter(RouterAdapter):
    def build(self, proposal):
        return TransactionEnvelope(
            chain_id=proposal.chain_id, from_address=proposal.wallet,
            to_address=proposal.router, value=0, data="0x1234",
            gas_limit=150_000, gas_price_wei=20_000_000_000,
            nonce=1, proposal_digest=proposal.digest(),
        )


class RecordingTestSigner:
    """Not isolated; only an observable signing-boundary test double."""
    def __init__(self, tamper=False):
        self.calls = 0
        self.tamper = tamper

    def sign(self, proposal, tx, approval):
        self.calls += 1
        return SignedTransaction(
            raw="0xf00d",
            proposal_digest=proposal.digest(),
            transaction_digest=("0" * 64 if self.tamper else tx.digest()),
        )


def intent():
    return TradeIntent(
        asset="ETH", direction=Direction.LONG, amount=1,
        size_bps=100, reason="bounded test", risk_score_bps=1000,
    )


def pipeline(signer, chain, approval_provider, store):
    return BoundaryPipeline(
        RiskEngine(), Policy(chain_id=1, wallet=WALLET, router=ROUTER),
        FixedRouter(), chain, signer,
        Timelock(threshold_bps=500, duration_seconds=172800),
        approval_provider=approval_provider, proposal_store=store,
    )


def approved(proposal, tx, simulation):
    assert simulation.passed
    return Approval.bind(proposal, tx, "fixture-approver")


def test_bounded_authorization_to_signed_payload_and_replay_block(tmp_path):
    path = str(tmp_path / "authorization.sqlite")
    signer, chain = RecordingTestSigner(), DeterministicChain()
    store = ProposalStore(path)
    boundary = pipeline(signer, chain, approved, store)
    result = boundary.execute(intent(), 0, request_id="fixture-1")
    assert result.status == ProposalStatus.SIGNED
    assert result.simulation.passed
    assert result.signed_transaction is not None
    result.signed_transaction.validate(result.proposal, result.transaction)
    assert signer.calls == 1
    assert chain.calls >= 4  # pre-approval and post-timelock simulations
    store.close()

    reopened = ProposalStore(path)
    retry = pipeline(signer, chain, approved, reopened).execute(
        intent(), 0, request_id="fixture-1"
    )
    assert retry.status == ProposalStatus.SIGNING_BLOCKED
    assert retry.signed_transaction is None
    assert signer.calls == 1
    reopened.close()


def test_simulation_failure_never_reaches_signer():
    signer = RecordingTestSigner()
    store = ProposalStore()
    result = pipeline(signer, DeterministicChain(fail=True), approved, store).execute(
        intent(), 0, request_id="simulation-fail"
    )
    assert result.status == ProposalStatus.SIMULATION_FAILED
    assert result.signed_transaction is None
    assert signer.calls == 0
    store.close()


def test_approval_mismatch_never_reaches_signer():
    signer = RecordingTestSigner()
    store = ProposalStore()

    def wrong_approval(proposal, tx, simulation):
        return replace(Approval.bind(proposal, tx, "fixture"), transaction_digest="0" * 64)

    result = pipeline(signer, DeterministicChain(), wrong_approval, store).execute(
        intent(), 0, request_id="approval-mismatch"
    )
    assert result.status == ProposalStatus.SIGNING_BLOCKED
    assert signer.calls == 0
    store.close()


def test_tampered_signed_envelope_is_rejected():
    signer = RecordingTestSigner(tamper=True)
    store = ProposalStore()
    result = pipeline(signer, DeterministicChain(), approved, store).execute(
        intent(), 0, request_id="tampered-signer-output"
    )
    assert result.status == ProposalStatus.SIGNING_BLOCKED
    assert result.signed_transaction is None
    assert signer.calls == 1
    store.close()


def test_default_signer_fails_closed():
    store = ProposalStore()
    result = pipeline(DisabledSigner(), DeterministicChain(), approved, store).execute(
        intent(), 0, request_id="default-signer"
    )
    assert result.status == ProposalStatus.SIGNING_BLOCKED
    assert "signing disabled" in result.reason
    assert result.signed_transaction is None
    store.close()
