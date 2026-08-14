from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Mapping


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class ProposalStatus(str, Enum):
    PROPOSED = "PROPOSED"
    POLICY_REJECTED = "POLICY_REJECTED"
    TIMELOCKED = "TIMELOCKED"
    SIMULATION_FAILED = "SIMULATION_FAILED"
    APPROVED = "APPROVED"
    SIGNING_BLOCKED = "SIGNING_BLOCKED"
    SIGNED = "SIGNED"
    BROADCAST = "BROADCAST"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class TradeIntent:
    asset: str
    direction: Direction
    amount: int
    size_bps: int
    reason: str
    risk_score_bps: int


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    requested_size_bps: int
    permitted_size_bps: int
    portfolio_exposure_bps: int
    risk_score_bps: int
    reason: str


@dataclass(frozen=True)
class TradeProposal:
    proposal_id: str
    created_at: int
    chain_id: int
    wallet: str
    router: str
    asset: str
    direction: Direction
    amount: int
    size_bps: int
    max_slippage_bps: int
    gas_price_limit_wei: int
    deadline: int
    policy_version: str
    reason: str
    risk_score_bps: int

    def canonical(self) -> str:
        payload = {
            "amount": self.amount,
            "asset": self.asset,
            "chain_id": self.chain_id,
            "created_at": self.created_at,
            "deadline": self.deadline,
            "direction": self.direction.value,
            "gas_price_limit_wei": self.gas_price_limit_wei,
            "max_slippage_bps": self.max_slippage_bps,
            "policy_version": self.policy_version,
            "proposal_id": self.proposal_id,
            "reason": self.reason,
            "risk_score_bps": self.risk_score_bps,
            "router": self.router,
            "size_bps": self.size_bps,
            "wallet": self.wallet,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TransactionEnvelope:
    chain_id: int
    from_address: str
    to_address: str
    value: int
    data: str
    gas_limit: int
    gas_price_wei: int
    nonce: int
    proposal_digest: str

    def canonical(self) -> str:
        payload = {
            "chain_id": self.chain_id,
            "data": self.data,
            "from": self.from_address,
            "gas_limit": self.gas_limit,
            "gas_price_wei": self.gas_price_wei,
            "nonce": self.nonce,
            "proposal_digest": self.proposal_digest,
            "to": self.to_address,
            "value": self.value,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def normalise_address(value: str) -> str:
    value = value.strip()
    if not value or not value.startswith("0x") or len(value) != 42:
        raise ValueError("invalid EVM address")
    return value.lower()


def validate_envelope_shape(tx: Mapping[str, object]) -> None:
    required = {
        "chain_id", "from", "to", "value", "data", "gas_limit",
        "gas_price_wei", "nonce", "proposal_digest",
    }
    missing = required - set(tx)
    if missing:
        raise ValueError(f"transaction missing fields: {sorted(missing)}")
    if not isinstance(tx["data"], str) or not tx["data"].startswith("0x"):
        raise ValueError("transaction calldata must be 0x-prefixed hex")
