from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .models import TradeProposal, TransactionEnvelope


@dataclass(frozen=True)
class SignedTransaction:
    """Opaque signed payload plus immutable identities it was authorized for."""

    raw: str
    proposal_digest: str
    transaction_digest: str

    def validate(self, proposal: TradeProposal, tx: TransactionEnvelope) -> None:
        if not self.raw.strip():
            raise ValueError("signed transaction is empty")
        if self.proposal_digest != proposal.digest():
            raise ValueError("signed transaction is not bound to proposal")
        if self.transaction_digest != tx.digest():
            raise ValueError("signed transaction is not bound to exact transaction")


@dataclass(frozen=True)
class BroadcastResult:
    tx_hash: str
    accepted: bool
    reason: str


class BroadcastGateway(ABC):
    """Submission boundary. Receives only an authorized signed transaction."""

    @abstractmethod
    def broadcast(
        self,
        signed_transaction: SignedTransaction,
        proposal: TradeProposal,
        tx: TransactionEnvelope,
    ) -> BroadcastResult:
        signed_transaction.validate(proposal, tx)
        raise NotImplementedError


class Verifier(ABC):
    """Post-broadcast verification boundary."""

    @abstractmethod
    def verify(
        self,
        proposal: TradeProposal,
        tx: TransactionEnvelope,
        tx_hash: str,
    ) -> bool:
        raise NotImplementedError
