from __future__ import annotations

from dataclasses import dataclass

from .models import RiskDecision


@dataclass(frozen=True)
class RiskLimits:
    max_position_bps: int = 1500
    max_portfolio_exposure_bps: int = 5000
    max_gas_price_gwei: int = 50
    max_slippage_bps: int = 100
    max_daily_loss_bps: int = 500


class RiskEngine:
    """Deterministic risk calculation. No wallet and no transaction access."""

    def __init__(self, limits: RiskLimits | None = None) -> None:
        self.limits = limits or RiskLimits()

    def evaluate(
        self,
        requested_size_bps: int,
        portfolio_exposure_bps: int,
        gas_price_gwei: int,
    ) -> RiskDecision:
        if requested_size_bps < 0:
            return self._reject(requested_size_bps, portfolio_exposure_bps, "negative size")
        if portfolio_exposure_bps < 0:
            return self._reject(requested_size_bps, portfolio_exposure_bps, "negative exposure")
        if gas_price_gwei > self.limits.max_gas_price_gwei:
            return self._reject(requested_size_bps, portfolio_exposure_bps, "gas limit exceeded")
        if portfolio_exposure_bps >= self.limits.max_portfolio_exposure_bps:
            return self._reject(requested_size_bps, portfolio_exposure_bps, "portfolio exposure limit reached")

        permitted = min(
            requested_size_bps,
            self.limits.max_position_bps,
            self.limits.max_portfolio_exposure_bps - portfolio_exposure_bps,
        )
        if permitted <= 0:
            return self._reject(requested_size_bps, portfolio_exposure_bps, "no permissible size")

        risk_score = min(
            10_000,
            max(0, 10_000 - (permitted * 10_000 // self.limits.max_position_bps)),
        )
        return RiskDecision(
            allowed=True,
            requested_size_bps=requested_size_bps,
            permitted_size_bps=permitted,
            portfolio_exposure_bps=portfolio_exposure_bps,
            risk_score_bps=risk_score,
            reason="risk limits passed",
        )

    @staticmethod
    def _reject(requested: int, exposure: int, reason: str) -> RiskDecision:
        return RiskDecision(
            allowed=False,
            requested_size_bps=max(0, requested),
            permitted_size_bps=0,
            portfolio_exposure_bps=max(0, exposure),
            risk_score_bps=10_000,
            reason=reason,
        )
