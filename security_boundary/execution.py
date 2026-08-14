from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .models import TradeProposal, TransactionEnvelope


@dataclass(frozen=True)
class BroadcastResult:
    tx_hash: str
    accepted: bool
    reason: str


class BroadcastGateway(ABC):
    """Submission boundary. Receives an opaque signed transaction only."""

    @abstractmethod
    def broadcast(self, signed_transaction: str) -> BroadcastResult:
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
