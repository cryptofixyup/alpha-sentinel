from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Approval:
    proposal_digest: str
    approved_at: int
    approver: str


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
