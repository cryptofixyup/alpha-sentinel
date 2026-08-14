from __future__ import annotations

import time
from dataclasses import dataclass

from .models import TradeProposal, TransactionEnvelope


@dataclass(frozen=True)
class Approval:
    """Authorization bound to both the immutable proposal and exact tx envelope."""

    proposal_digest: str
    transaction_digest: str
    approved_at: int
    approver: str

    @classmethod
    def bind(
        cls,
        proposal: TradeProposal,
        transaction: TransactionEnvelope,
        approver: str,
        approved_at: int | None = None,
    ) -> "Approval":
        if not approver.strip():
            raise ValueError("approver is required")
        return cls(
            proposal_digest=proposal.digest(),
            transaction_digest=transaction.digest(),
            approved_at=int(time.time()) if approved_at is None else approved_at,
            approver=approver,
        )


def validate_approval(
    proposal: TradeProposal,
    transaction: TransactionEnvelope,
    approval: Approval,
) -> None:
    if approval.proposal_digest != proposal.digest():
        raise PermissionError("approval is not bound to proposal")
    if approval.transaction_digest != transaction.digest():
        raise PermissionError("approval is not bound to exact transaction envelope")


class Timelock:
    def __init__(self, threshold_bps: int = 500, duration_seconds: int = 172800) -> None:
        self.threshold_bps = threshold_bps
        self.duration_seconds = duration_seconds
        self._unlock: dict[str, int] = {}

    def require(self, proposal_id: str, size_bps: int) -> int | None:
        if size_bps <= self.threshold_bps:
            return None
        unlock_at = self._unlock.get(proposal_id)
        if unlock_at is None:
            unlock_at = int(time.time()) + self.duration_seconds
            self._unlock[proposal_id] = unlock_at
        return unlock_at

    def ready(self, proposal_id: str, size_bps: int) -> bool:
        unlock_at = self.require(proposal_id, size_bps)
        return unlock_at is None or int(time.time()) >= unlock_at
