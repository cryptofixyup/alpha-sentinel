from __future__ import annotations

from dataclasses import dataclass

from .models import Direction, RiskDecision, TradeIntent, normalise_address
from .risk import RiskLimits


@dataclass(frozen=True)
class Policy:
    chain_id: int
    wallet: str
    router: str
    version: str = "alpha-sentinel-boundary-v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "wallet", normalise_address(self.wallet))
        object.__setattr__(self, "router", normalise_address(self.router))

    def authorize(self, intent: TradeIntent, risk: RiskDecision) -> None:
        if not risk.allowed:
            raise PermissionError(f"risk rejected: {risk.reason}")
        if intent.amount <= 0:
            raise PermissionError("amount must be positive")
        if intent.size_bps != risk.permitted_size_bps:
            raise PermissionError("intent size differs from risk authorization")
        if risk.permitted_size_bps > RiskLimits().max_position_bps:
            raise PermissionError("position hard limit exceeded")
        if intent.direction not in (Direction.LONG, Direction.SHORT):
            raise PermissionError("invalid direction")
