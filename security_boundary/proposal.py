from __future__ import annotations

import time
import uuid

from .models import TradeIntent, TradeProposal
from .policy import Policy


def make_proposal(
    intent: TradeIntent,
    policy: Policy,
    risk_score_bps: int,
    max_slippage_bps: int,
    gas_price_limit_wei: int,
    deadline_seconds: int = 300,
) -> TradeProposal:
    if deadline_seconds <= 0:
        raise ValueError("deadline must be positive")
    if max_slippage_bps < 0 or max_slippage_bps > 10_000:
        raise ValueError("invalid slippage")

    return TradeProposal(
        proposal_id=str(uuid.uuid4()),
        created_at=int(time.time()),
        chain_id=policy.chain_id,
        wallet=policy.wallet,
        router=policy.router,
        asset=intent.asset,
        direction=intent.direction,
        amount=intent.amount,
        size_bps=intent.size_bps,
        max_slippage_bps=max_slippage_bps,
        gas_price_limit_wei=gas_price_limit_wei,
        deadline=int(time.time()) + deadline_seconds,
        policy_version=policy.version,
        reason=intent.reason,
        risk_score_bps=risk_score_bps,
    )
