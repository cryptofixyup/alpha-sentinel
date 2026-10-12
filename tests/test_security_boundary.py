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
    def ready(self, proposal_id, size_bps, created_at=None):
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
    assert "cryptographically bound to proposal" in result.reason
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


def test_non_hex_evm_address_is_rejected():
    from security_boundary.models import normalise_address

    with pytest.raises(ValueError, match="invalid EVM address"):
        normalise_address("0x" + ("1" * 39) + "g")


def test_non_hex_calldata_is_rejected():
    from security_boundary.models import validate_envelope_shape

    envelope = {
        "chain_id": 1,
        "from": WALLET,
        "to": ROUTER,
        "value": 0,
        "data": "0xNOTHEX",
        "gas_limit": 150_000,
        "gas_price_wei": 20_000_000_000,
        "nonce": 1,
        "proposal_digest": "0" * 64,
    }

    with pytest.raises(ValueError, match="0x-prefixed hex"):
        validate_envelope_shape(envelope)


def test_transaction_gas_price_cannot_exceed_proposal_limit():
    class OverCapRouter(RouterAdapter):
        def build(self, proposal):
            return TransactionEnvelope(
                chain_id=proposal.chain_id,
                from_address=proposal.wallet,
                to_address=proposal.router,
                value=0,
                data="0x1234",
                gas_limit=150_000,
                gas_price_wei=proposal.gas_price_limit_wei + 1,
                nonce=1,
                proposal_digest=proposal.digest(),
            )

    result = make_pipeline(OverCapRouter()).execute(intent(), 0)

    assert result.status == ProposalStatus.FAILED
    assert "gas price exceeds proposal limit" in result.reason
    assert result.signed_transaction is None


@pytest.mark.parametrize("data", ["0xNOTHEX", "0x123", "1234", None])
def test_pipeline_rejects_invalid_calldata_before_simulation(data):
    class BadRouter(FakeRouter):
        def build(self, proposal):
            return replace(super().build(proposal), data=data)

    class NoSimulation(FakeChain):
        def estimate_gas(self, tx):
            pytest.fail("malformed calldata reached simulation")

    result = make_pipeline(BadRouter(), chain=NoSimulation()).execute(intent(), 0)
    assert result.status == ProposalStatus.FAILED
    assert "hex bytes" in result.reason


def test_large_trade_resumes_exact_envelope_after_process_restart(tmp_path, monkeypatch):
    from security_boundary.store import ProposalStore

    now = [1000]
    monkeypatch.setattr("time.time", lambda: now[0])
    path = str(tmp_path / "proposals.sqlite")
    first = make_pipeline(FakeRouter())
    first.proposal_store.close()
    first.proposal_store = ProposalStore(path)
    waiting = first.execute(intent(600), 0, request_id="trade-1")
    assert waiting.status == ProposalStatus.TIMELOCKED
    assert waiting.proposal.deadline == 1000 + 172800 + 300
    first.proposal_store.close()

    class NoRebuild(FakeRouter):
        def build(self, proposal):
            pytest.fail("persisted transaction was rebuilt")

    resumed = make_pipeline(NoRebuild())
    resumed.proposal_store.close()
    resumed.proposal_store = ProposalStore(path)
    now[0] += 172800
    ready = resumed.execute(intent(600), 0, request_id="trade-1")
    assert ready.status == ProposalStatus.SIGNING_BLOCKED
    assert "approval provider" in ready.reason
    assert ready.proposal == waiting.proposal
    assert ready.transaction == waiting.transaction
    assert ready.simulation.passed
    now[0] += 300
    expired = resumed.execute(intent(600), 0, request_id="trade-1")
    assert expired.status == ProposalStatus.FAILED
    assert expired.reason == "proposal expired"
    resumed.proposal_store.close()


def test_approval_cannot_extend_expired_proposal(monkeypatch):
    now = [1000]
    monkeypatch.setattr("time.time", lambda: now[0])

    def slow_approval(proposal, tx, simulation):
        now[0] = proposal.deadline
        return Approval.bind(proposal, tx, "approver")

    result = make_pipeline(FakeRouter(), approvals=slow_approval).execute(intent(), 0)
    assert result.status == ProposalStatus.SIGNING_BLOCKED
    assert result.reason == "proposal expired before signing"


def test_request_identity_rejects_changed_intent():
    pipeline = make_pipeline(FakeRouter())
    pipeline.execute(intent(), 0, request_id="trade-1")
    result = pipeline.execute(intent(200), 0, request_id="trade-1")
    assert result.status == ProposalStatus.FAILED
    assert "different intent or policy" in result.reason


def test_signing_attempt_is_not_repeated_after_restart(tmp_path):
    from security_boundary.store import ProposalStore

    calls = []

    class RecordingSigner:
        def sign(self, proposal, tx, approval):
            calls.append(proposal.proposal_id)
            return SignedTransaction("0xf00d", proposal.digest(), tx.digest())

    def approve(proposal, tx, simulation):
        return Approval.bind(proposal, tx, "approver")

    path = str(tmp_path / "proposals.sqlite")
    pipeline = make_pipeline(FakeRouter(), approvals=approve)
    pipeline.proposal_store.close()
    pipeline.proposal_store = ProposalStore(path)
    pipeline.signer = RecordingSigner()
    first = pipeline.execute(intent(), 0, request_id="trade-1")
    assert first.status == ProposalStatus.SIGNED
    pipeline.proposal_store.close()
    pipeline.proposal_store = ProposalStore(path)
    second = pipeline.execute(intent(), 0, request_id="trade-1")
    assert second.status == ProposalStatus.SIGNING_BLOCKED
    assert "reconciliation required" in second.reason
    assert len(calls) == 1
    assert pipeline.execute(intent(), 0, request_id="trade-2").status == ProposalStatus.SIGNED
    assert len(calls) == 2
    pipeline.proposal_store.close()


def test_signing_claim_is_atomic_across_store_connections(tmp_path):
    from security_boundary.store import ProposalStore

    path = str(tmp_path / "proposals.sqlite")
    a, b = ProposalStore(path), ProposalStore(path)
    result = make_pipeline(FakeRouter()).execute(intent(), 0)
    a.save("trade", "fingerprint", result.proposal, result.transaction)
    assert a.claim_signing("trade")
    assert not b.claim_signing("trade")
    a.close()
    b.close()
