from __future__ import annotations

from abc import ABC, abstractmethod

from .models import TradeProposal, TransactionEnvelope
from .router import validate_built_transaction


class IsolatedSigner(ABC):
    """Signer boundary. The orchestration process must not hold private keys."""

    @abstractmethod
    def sign(
        self,
        proposal: TradeProposal,
        tx: TransactionEnvelope,
    ) -> str:
        raise NotImplementedError


class DisabledSigner(IsolatedSigner):
    """Default signer: safe for development and CI; never signs."""

    def sign(self, proposal: TradeProposal, tx: TransactionEnvelope) -> str:
        validate_built_transaction(proposal, tx)
        raise RuntimeError("signing disabled: isolated signer not configured")
