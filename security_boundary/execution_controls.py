"""Fail-closed, deterministic pre-trade gates. No model or wallet access."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Mapping


class MevPolicy(str, Enum):
    REJECT = "REJECT"
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"
    SHADOW = "SHADOW"


@dataclass(frozen=True)
class MarketEvidence:
    """Versioned evidence required to authorize a live trade attempt.

    expected_value_bps must be net of fees, gas, slippage, adverse selection and
    the configured MEV allowance. probability_calibrated must be asserted by a
    separately governed calibration process; a raw model score is not enough.
    """
    observed_at: int
    now: int
    probability_calibrated: bool
    expected_value_bps: float
    liquidity_usd: float
    requested_notional_usd: float
    expected_slippage_bps: float
    mev_policy: MevPolicy
    private_route_available: bool
    daily_loss_bps: int
    portfolio_exposure_bps: int
    idempotency_key: str


@dataclass(frozen=True)
class ExecutionLimits:
    max_evidence_age_seconds: int = 15
    min_net_expected_value_bps: float = 10.0
    min_liquidity_multiple: float = 5.0
    max_slippage_bps: float = 100.0
    max_daily_loss_bps: int = 500
    max_portfolio_exposure_bps: int = 5000


class ExecutionGate:
    """Pure gate: missing, malformed, stale or unsafe evidence always rejects."""

    def __init__(self, limits: ExecutionLimits | None = None, *, kill_switch: bool = False):
        self.limits = limits or ExecutionLimits()
        self.kill_switch = kill_switch

    def evaluate(self, evidence: MarketEvidence | Mapping[str, object]) -> None:
        if self.kill_switch:
            raise PermissionError("KILL_SWITCH_ACTIVE")
        if isinstance(evidence, Mapping):
            try:
                evidence = MarketEvidence(**evidence)
            except (TypeError, ValueError) as exc:
                raise PermissionError("MARKET_EVIDENCE_INVALID") from exc
        if not isinstance(evidence, MarketEvidence):
            raise PermissionError("MARKET_EVIDENCE_REQUIRED")
        if not evidence.idempotency_key or not isinstance(evidence.idempotency_key, str):
            raise PermissionError("IDEMPOTENCY_KEY_REQUIRED")
        if not isinstance(evidence.observed_at, int) or not isinstance(evidence.now, int):
            raise PermissionError("MARKET_TIMESTAMP_INVALID")
        age = evidence.now - evidence.observed_at
        if age < 0 or age > self.limits.max_evidence_age_seconds:
            raise PermissionError("MARKET_EVIDENCE_STALE")
        if evidence.probability_calibrated is not True:
            raise PermissionError("CALIBRATED_PROBABILITY_REQUIRED")
        numeric = (
            evidence.expected_value_bps, evidence.liquidity_usd,
            evidence.requested_notional_usd, evidence.expected_slippage_bps,
        )
        if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) for v in numeric):
            raise PermissionError("MARKET_METRIC_INVALID")
        if evidence.expected_value_bps < self.limits.min_net_expected_value_bps:
            raise PermissionError("NET_EXPECTED_VALUE_BELOW_FLOOR")
        if evidence.requested_notional_usd <= 0 or evidence.liquidity_usd <= 0:
            raise PermissionError("LIQUIDITY_OR_NOTIONAL_INVALID")
        if evidence.liquidity_usd < evidence.requested_notional_usd * self.limits.min_liquidity_multiple:
            raise PermissionError("LIQUIDITY_TOO_LOW")
        if evidence.expected_slippage_bps < 0 or evidence.expected_slippage_bps > self.limits.max_slippage_bps:
            raise PermissionError("SLIPPAGE_LIMIT_EXCEEDED")
        if not isinstance(evidence.daily_loss_bps, int) or evidence.daily_loss_bps < 0:
            raise PermissionError("DAILY_LOSS_INVALID")
        if evidence.daily_loss_bps >= self.limits.max_daily_loss_bps:
            raise PermissionError("DAILY_LOSS_LIMIT_REACHED")
        if not isinstance(evidence.portfolio_exposure_bps, int) or evidence.portfolio_exposure_bps < 0:
            raise PermissionError("PORTFOLIO_EXPOSURE_INVALID")
        if evidence.portfolio_exposure_bps >= self.limits.max_portfolio_exposure_bps:
            raise PermissionError("PORTFOLIO_EXPOSURE_LIMIT_REACHED")
        try:
            policy = MevPolicy(evidence.mev_policy)
        except (TypeError, ValueError) as exc:
            raise PermissionError("MEV_POLICY_INVALID") from exc
        if policy in (MevPolicy.REJECT, MevPolicy.SHADOW):
            raise PermissionError("MEV_POLICY_BLOCKS_LIVE_EXECUTION")
        if policy is MevPolicy.PRIVATE and evidence.private_route_available is not True:
            raise PermissionError("PRIVATE_ROUTE_REQUIRED")
        if policy is MevPolicy.PUBLIC and evidence.private_route_available is not False:
            # A public route is permitted only when explicitly selected; private
            # route presence must not silently change the approved execution path.
            raise PermissionError("MEV_ROUTE_POLICY_MISMATCH")
