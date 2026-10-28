"""Fail-closed, durable post-signing broadcast and receipt settlement boundary.

Production must inject a chain-specific gateway/verifier tested against the target
chain and a persistent shared execution-state store. This module does not implement
RPC/provider semantics or private-key custody.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Protocol

from .execution import BroadcastResult, SignedTransaction
from .execution_state import SQLiteExecutionState
from .models import TradeProposal, TransactionEnvelope


_TX_HASH = re.compile(r"^0x[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class ReceiptEvidence:
    tx_hash: str
    chain_id: int
    proposal_digest: str
    transaction_digest: str
    success: bool
    confirmations: int
    required_confirmations: int
    canonical: bool


@dataclass(frozen=True)
class SettlementResult:
    status: str
    tx_hash: str | None
    reason: str


class SettlementGateway(Protocol):
    def broadcast(
        self, signed_transaction: SignedTransaction, proposal: TradeProposal,
        tx: TransactionEnvelope,
    ) -> BroadcastResult: ...


class ReceiptVerifier(Protocol):
    def verify_receipt(
        self, proposal: TradeProposal, tx: TransactionEnvelope, tx_hash: str,
    ) -> ReceiptEvidence: ...


class SettlementCoordinator:
    """Persist an idempotency claim before broadcast; never retry ambiguous submission."""

    def __init__(
        self,
        gateway: SettlementGateway,
        verifier: ReceiptVerifier,
        state_store: SQLiteExecutionState,
    ):
        if state_store is None:
            raise ValueError("persistent execution-state store required")
        self.gateway = gateway
        self.verifier = verifier
        self.state_store = state_store

    def settle(
        self,
        signed: SignedTransaction,
        proposal: TradeProposal,
        tx: TransactionEnvelope,
        *,
        idempotency_key: str | None = None,
    ) -> SettlementResult:
        try:
            signed.validate(proposal, tx)
        except Exception as exc:
            return SettlementResult("FAILED", None, f"signed payload binding failed: {exc}")

        key = proposal.proposal_id if idempotency_key is None else idempotency_key
        if not isinstance(key, str) or not key.strip():
            return SettlementResult("FAILED", None, "idempotency key required")
        raw_digest = hashlib.sha256(signed.raw.encode("utf-8")).hexdigest()
        payload_digest = hashlib.sha256(
            f"{signed.proposal_digest}:{signed.transaction_digest}:{raw_digest}".encode("utf-8")
        ).hexdigest()
        try:
            first_claim, prior_state, known_hash = self.state_store.claim_broadcast(key, payload_digest)
        except Exception as exc:
            return SettlementResult("FAILED", None, f"durable broadcast claim failed: {exc}")

        if not first_claim:
            if prior_state == "FAILED":
                return SettlementResult("FAILED", known_hash, "prior broadcast attempt is terminally failed")
            if prior_state == "IN_FLIGHT" and known_hash is None:
                return SettlementResult(
                    "RECONCILIATION_REQUIRED", None,
                    "prior broadcast claim is unresolved; refusing duplicate submission",
                )
            if prior_state == "RECONCILIATION_REQUIRED" and known_hash is None:
                return SettlementResult(
                    "RECONCILIATION_REQUIRED", None,
                    "broadcast outcome is ambiguous; reconcile by idempotency key before retry",
                )
            if known_hash is None or not _TX_HASH.fullmatch(known_hash):
                return SettlementResult("RECONCILIATION_REQUIRED", known_hash, "journal transaction hash unavailable or invalid")
            tx_hash = known_hash
        else:
            try:
                broadcast = self.gateway.broadcast(signed, proposal, tx)
            except Exception as exc:
                self.state_store.record_broadcast(key, payload_digest, "RECONCILIATION_REQUIRED", None)
                return SettlementResult("RECONCILIATION_REQUIRED", None, f"broadcast outcome ambiguous: {exc}")
            if not isinstance(broadcast, BroadcastResult):
                self.state_store.record_broadcast(key, payload_digest, "FAILED", None)
                return SettlementResult("FAILED", None, "invalid broadcast response")
            if not isinstance(broadcast.tx_hash, str) or not _TX_HASH.fullmatch(broadcast.tx_hash):
                self.state_store.record_broadcast(key, payload_digest, "FAILED", None)
                return SettlementResult("FAILED", None, "invalid transaction hash")
            tx_hash = broadcast.tx_hash
            if broadcast.accepted is not True:
                self.state_store.record_broadcast(key, payload_digest, "FAILED", tx_hash)
                return SettlementResult("FAILED", tx_hash, broadcast.reason or "broadcast rejected")
            self.state_store.record_broadcast(key, payload_digest, "BROADCAST", tx_hash)

        try:
            receipt = self.verifier.verify_receipt(proposal, tx, tx_hash)
        except Exception as exc:
            self.state_store.record_broadcast(key, payload_digest, "RECONCILIATION_REQUIRED", tx_hash)
            return SettlementResult("RECONCILIATION_REQUIRED", tx_hash, f"receipt verification unavailable: {exc}")
        if not isinstance(receipt, ReceiptEvidence):
            self.state_store.record_broadcast(key, payload_digest, "RECONCILIATION_REQUIRED", tx_hash)
            return SettlementResult("RECONCILIATION_REQUIRED", tx_hash, "receipt evidence unavailable")
        if receipt.tx_hash.lower() != tx_hash.lower():
            self.state_store.record_broadcast(key, payload_digest, "FAILED", tx_hash)
            return SettlementResult("FAILED", tx_hash, "receipt transaction hash mismatch")
        if receipt.chain_id != proposal.chain_id:
            self.state_store.record_broadcast(key, payload_digest, "FAILED", tx_hash)
            return SettlementResult("FAILED", tx_hash, "receipt chain mismatch")
        if receipt.proposal_digest != proposal.digest() or receipt.transaction_digest != tx.digest():
            self.state_store.record_broadcast(key, payload_digest, "FAILED", tx_hash)
            return SettlementResult("FAILED", tx_hash, "receipt does not bind to authorized proposal and transaction")
        if receipt.success is not True:
            self.state_store.record_broadcast(key, payload_digest, "FAILED", tx_hash)
            return SettlementResult("FAILED", tx_hash, "on-chain transaction reverted")
        if receipt.canonical is not True:
            self.state_store.record_broadcast(key, payload_digest, "RECONCILIATION_REQUIRED", tx_hash)
            return SettlementResult("RECONCILIATION_REQUIRED", tx_hash, "receipt is non-canonical or reorg status unknown")
        if (
            not isinstance(receipt.confirmations, int) or isinstance(receipt.confirmations, bool)
            or not isinstance(receipt.required_confirmations, int)
            or isinstance(receipt.required_confirmations, bool)
            or receipt.required_confirmations < 1
            or receipt.confirmations < receipt.required_confirmations
        ):
            self.state_store.record_broadcast(key, payload_digest, "BROADCAST", tx_hash)
            return SettlementResult("BROADCAST", tx_hash, "awaiting required confirmations")
        self.state_store.record_broadcast(key, payload_digest, "CONFIRMED", tx_hash)
        return SettlementResult("CONFIRMED", tx_hash, "receipt verified and confirmation threshold met")
