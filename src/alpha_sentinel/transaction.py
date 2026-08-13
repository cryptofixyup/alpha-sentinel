from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from typing import Any, Mapping


class PipelineViolation(ValueError):
    """Raised when a security invariant cannot be proven."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


class LifecycleState(str, Enum):
    PROPOSED = "PROPOSED"
    SIMULATED = "SIMULATED"
    APPROVED = "APPROVED"
    SIGNED = "SIGNED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class Proposal:
    proposal_id: str
    router_id: str
    payload: Any
    metadata: Mapping[str, Any] = field(default_factory=dict)
    proposal_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.proposal_id or not self.router_id:
            raise PipelineViolation("proposal_id and router_id are required")
        object.__setattr__(self, "proposal_hash", canonical_hash({
            "proposal_id": self.proposal_id,
            "router_id": self.router_id,
            "payload": self.payload,
            "metadata": self.metadata,
        }))


@dataclass(frozen=True, slots=True)
class TransactionIntent:
    proposal_hash: str
    chain_id: str
    nonce: int
    to: str
    value: int
    data: bytes = b""

    def __post_init__(self) -> None:
        if not self.proposal_hash or not self.chain_id or self.nonce < 0 or self.value < 0 or not self.to:
            raise PipelineViolation("invalid transaction intent")


@dataclass(frozen=True, slots=True)
class BoundTransaction:
    intent: TransactionIntent
    simulation_hash: str
    binding_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.simulation_hash:
            raise PipelineViolation("simulation_hash is required")
        object.__setattr__(self, "binding_hash", canonical_hash({
            "proposal_hash": self.intent.proposal_hash,
            "chain_id": self.intent.chain_id,
            "nonce": self.intent.nonce,
            "to": self.intent.to,
            "value": self.intent.value,
            "data": self.intent.data.hex(),
            "simulation_hash": self.simulation_hash,
        }))


@dataclass(frozen=True, slots=True)
class Approval:
    proposal_hash: str
    binding_hash: str
    approver: str
    approval_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.approver:
            raise PipelineViolation("approver is required")
        object.__setattr__(self, "approval_hash", canonical_hash({
            "proposal_hash": self.proposal_hash,
            "binding_hash": self.binding_hash,
            "approver": self.approver,
        }))


@dataclass(frozen=True, slots=True)
class AuditEvent:
    state: LifecycleState
    subject_hash: str
    previous_hash: str
    event_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_hash", canonical_hash({
            "state": self.state.value,
            "subject_hash": self.subject_hash,
            "previous_hash": self.previous_hash,
        }))


def audit_event(state: LifecycleState, subject_hash: str, previous_hash: str = "") -> AuditEvent:
    return AuditEvent(state, subject_hash, previous_hash)


def bind_transaction(intent: TransactionIntent, simulation_hash: str) -> BoundTransaction:
    return BoundTransaction(intent, simulation_hash)


def approve(bound: BoundTransaction, proposal_hash: str, approver: str) -> Approval:
    if proposal_hash != bound.intent.proposal_hash:
        raise PipelineViolation("proposal hash does not match bound transaction")
    return Approval(proposal_hash, bound.binding_hash, approver)


def transition(current: LifecycleState, target: LifecycleState, *, subject_hash: str, previous_audit_hash: str = "") -> AuditEvent:
    allowed = {
        LifecycleState.PROPOSED: {LifecycleState.SIMULATED, LifecycleState.REJECTED},
        LifecycleState.SIMULATED: {LifecycleState.APPROVED, LifecycleState.REJECTED},
        LifecycleState.APPROVED: {LifecycleState.SIGNED, LifecycleState.REJECTED},
        LifecycleState.SIGNED: set(),
        LifecycleState.REJECTED: set(),
    }
    if target not in allowed[current]:
        raise PipelineViolation(f"illegal lifecycle transition: {current.value} -> {target.value}")
    return audit_event(target, subject_hash, previous_audit_hash)


def verify_audit_chain(events: tuple[AuditEvent, ...]) -> None:
    previous = ""
    for event in events:
        if event.previous_hash != previous:
            raise PipelineViolation("audit chain is broken")
        expected = canonical_hash({
            "state": event.state.value,
            "subject_hash": event.subject_hash,
            "previous_hash": event.previous_hash,
        })
        if event.event_hash != expected:
            raise PipelineViolation("audit event has been mutated")
        previous = event.event_hash
