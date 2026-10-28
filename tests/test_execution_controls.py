import pytest

from security_boundary.execution_controls import (
    ExecutionGate, ExecutionLimits, MarketEvidence, MevPolicy,
)


def evidence(**overrides):
    values = dict(
        observed_at=100, now=105, probability_calibrated=True,
        expected_value_bps=25.0, liquidity_usd=100_000.0,
        requested_notional_usd=10_000.0, expected_slippage_bps=25.0,
        mev_policy=MevPolicy.PRIVATE, private_route_available=True,
        daily_loss_bps=100, portfolio_exposure_bps=1000,
        idempotency_key="trade-001",
    )
    values.update(overrides)
    return MarketEvidence(**values)


def test_valid_private_route_evidence_passes():
    assert ExecutionGate().evaluate(evidence()) is None


@pytest.mark.parametrize(("overrides", "error"), [
    ({"observed_at": 1, "now": 100}, "MARKET_EVIDENCE_STALE"),
    ({"observed_at": 106, "now": 105}, "MARKET_EVIDENCE_STALE"),
    ({"probability_calibrated": False}, "CALIBRATED_PROBABILITY_REQUIRED"),
    ({"expected_value_bps": 9.99}, "NET_EXPECTED_VALUE_BELOW_FLOOR"),
    ({"liquidity_usd": 49_999}, "LIQUIDITY_TOO_LOW"),
    ({"expected_slippage_bps": 101}, "SLIPPAGE_LIMIT_EXCEEDED"),
    ({"daily_loss_bps": 500}, "DAILY_LOSS_LIMIT_REACHED"),
    ({"portfolio_exposure_bps": 5000}, "PORTFOLIO_EXPOSURE_LIMIT_REACHED"),
    ({"mev_policy": MevPolicy.REJECT}, "MEV_POLICY_BLOCKS_LIVE_EXECUTION"),
    ({"mev_policy": MevPolicy.SHADOW}, "MEV_POLICY_BLOCKS_LIVE_EXECUTION"),
    ({"mev_policy": MevPolicy.PRIVATE, "private_route_available": False}, "PRIVATE_ROUTE_REQUIRED"),
    ({"mev_policy": MevPolicy.PUBLIC, "private_route_available": True}, "MEV_ROUTE_POLICY_MISMATCH"),
    ({"idempotency_key": ""}, "IDEMPOTENCY_KEY_REQUIRED"),
    ({"expected_value_bps": float("nan")}, "MARKET_METRIC_INVALID"),
])
def test_unsafe_or_invalid_evidence_fails_closed(overrides, error):
    with pytest.raises(PermissionError, match=error):
        ExecutionGate().evaluate(evidence(**overrides))


def test_kill_switch_rejects_even_valid_evidence():
    with pytest.raises(PermissionError, match="KILL_SWITCH_ACTIVE"):
        ExecutionGate(kill_switch=True).evaluate(evidence())


def test_unknown_or_missing_evidence_fails_closed():
    gate = ExecutionGate()
    with pytest.raises(PermissionError, match="MARKET_EVIDENCE_REQUIRED"):
        gate.evaluate(None)
    with pytest.raises(PermissionError, match="MARKET_EVIDENCE_INVALID"):
        gate.evaluate({"observed_at": "bad"})


def test_custom_limits_are_applied():
    gate = ExecutionGate(ExecutionLimits(min_net_expected_value_bps=30))
    with pytest.raises(PermissionError, match="NET_EXPECTED_VALUE_BELOW_FLOOR"):
        gate.evaluate(evidence(expected_value_bps=25))


def test_configured_pipeline_gate_rejects_before_simulator_or_router():
    from security_boundary.pipeline import BoundaryPipeline
    from security_boundary.models import Direction, ProposalStatus, TradeIntent

    class NeverSimulator:
        def gas_price(self):
            pytest.fail("execution evidence must be checked before simulator access")

    pipeline = BoundaryPipeline(
        risk=None, policy=None, router=None, simulator=NeverSimulator(), signer=None,
        execution_gate=ExecutionGate(),
    )
    result = pipeline.execute(
        TradeIntent("ETH", Direction.LONG, 1, 100, "test", 100),
        0,
        request_id="test-guard",
    )
    assert result.status is ProposalStatus.POLICY_REJECTED
    assert result.reason == "MARKET_EVIDENCE_REQUIRED"
    assert result.signed_transaction is None
