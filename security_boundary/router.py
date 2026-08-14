from __future__ import annotations

from abc import ABC, abstractmethod

from .models import TradeProposal, TransactionEnvelope, normalise_address


class RouterAdapter(ABC):
    """Chain/router-specific transaction construction boundary."""

    @abstractmethod
    def build(self, proposal: TradeProposal) -> TransactionEnvelope:
        """Build exact calldata from an already-authorized proposal."""
        raise NotImplementedError


class UnconfiguredRouterAdapter(RouterAdapter):
    """Explicit fail-closed placeholder until a real router ABI is configured."""

    def build(self, proposal: TradeProposal) -> TransactionEnvelope:
        raise RuntimeError(
            "router adapter is not configured; refusing to fabricate calldata"
        )


def validate_built_transaction(
    proposal: TradeProposal,
    tx: TransactionEnvelope,
) -> None:
    if tx.chain_id != proposal.chain_id:
        raise ValueError("transaction chain differs from proposal")
    if normalise_address(tx.from_address) != normalise_address(proposal.wallet):
        raise ValueError("transaction sender differs from proposal")
    if normalise_address(tx.to_address) != normalise_address(proposal.router):
        raise ValueError("transaction target differs from proposal")
    if tx.proposal_digest != proposal.digest():
        raise ValueError("transaction is not cryptographically bound to proposal")
    if not tx.data.startswith("0x"):
        raise ValueError("transaction calldata must be 0x-prefixed")
    if tx.value < 0 or tx.gas_limit <= 0 or tx.gas_price_wei < 0 or tx.nonce < 0:
        raise ValueError("invalid transaction numeric field")
