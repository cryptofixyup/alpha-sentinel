from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import TradeProposal, TransactionEnvelope
from .router import validate_built_transaction


class ChainSimulator(Protocol):
    def estimate_gas(self, tx: dict) -> int: ...
    def call(self, tx: dict) -> None: ...
    def gas_price(self) -> int: ...


@dataclass(frozen=True)
class SimulationResult:
    passed: bool
    estimated_gas: int
    reason: str


def simulate(
    proposal: TradeProposal,
    tx: TransactionEnvelope,
    chain: ChainSimulator,
) -> SimulationResult:
    try:
        validate_built_transaction(proposal, tx)
        if chain.gas_price() > proposal.gas_price_limit_wei:
            return SimulationResult(False, 0, "gas price exceeds proposal limit")

        raw = {
            "chainId": tx.chain_id,
            "from": tx.from_address,
            "to": tx.to_address,
            "value": tx.value,
            "data": tx.data,
            "gas": tx.gas_limit,
            "gasPrice": tx.gas_price_wei,
            "nonce": tx.nonce,
        }
        estimated = chain.estimate_gas(raw)
        if estimated <= 0 or estimated > tx.gas_limit:
            return SimulationResult(False, estimated, "gas estimate outside envelope")
        chain.call(raw)
        return SimulationResult(True, estimated, "eth_call and gas estimation passed")
    except Exception as exc:
        return SimulationResult(False, 0, f"simulation failed: {exc}")
