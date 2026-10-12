from __future__ import annotations

from abc import ABC, abstractmethod

from .approval import Approval, validate_approval
from .execution import SignedTransaction
from .models import TradeProposal, TransactionEnvelope
from .router import validate_built_transaction


class IsolatedSigner(ABC):
    """Signer boundary. The orchestration process must not hold private keys."""

    @abstractmethod
    def sign(
        self,
        proposal: TradeProposal,
        tx: TransactionEnvelope,
        approval: Approval,
    ) -> SignedTransaction:
        raise NotImplementedError


class DisabledSigner(IsolatedSigner):
    """Default signer: safe for development and CI; never signs."""

    def sign(
        self,
        proposal: TradeProposal,
        tx: TransactionEnvelope,
        approval: Approval,
    ) -> SignedTransaction:
        validate_built_transaction(proposal, tx)
        validate_approval(proposal, tx, approval)
        raise RuntimeError("signing disabled: isolated signer not configured")
