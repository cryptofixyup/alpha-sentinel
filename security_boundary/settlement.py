"""Fail-closed post-signing broadcast and receipt settlement boundary.

This module deliberately contains no RPC implementation or private key handling.
Production must supply a chain-specific gateway and verifier whose behavior is
tested against the target chain/provider before enabling live execution.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol

from .execution import BroadcastResult, SignedTransaction
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
    """Broadcast once per call; never reports success without verified finality.

    Durable idempotency across process restarts must be provided by the caller's
    persistent job/store layer. A duplicate broadcast response must return the
    same transaction hash, and production implementations must reconcile by
    idempotency key before resubmission after an ambiguous network failure.
    """

    def __init__(self, gateway: SettlementGateway, verifier: ReceiptVerifier):
        self.gateway = gateway
        self.verifier = verifier

    def settle(
        self, signed: SignedTransaction, proposal: TradeProposal,
        tx: TransactionEnvelope,
    ) -> SettlementResult:
        try:
            signed.validate(proposal, tx)
        except Exception as exc:
            return SettlementResult("FAILED", None, f"signed payload binding failed: {exc}")

        try:
            broadcast = self.gateway.broadcast(signed, proposal, tx)
        except Exception as exc:
            return SettlementResult("RECONCILIATION_REQUIRED", None, f"broadcast outcome ambiguous: {exc}")
        if not isinstance(broadcast, BroadcastResult):
            return SettlementResult("FAILED", None, "invalid broadcast response")
        if not isinstance(broadcast.tx_hash, str) or not _TX_HASH.fullmatch(broadcast.tx_hash):
            return SettlementResult("FAILED", None, "invalid transaction hash")
        if broadcast.accepted is not True:
            return SettlementResult("FAILED", broadcast.tx_hash, broadcast.reason or "broadcast rejected")

        try:
            receipt = self.verifier.verify_receipt(proposal, tx, broadcast.tx_hash)
        except Exception as exc:
            return SettlementResult("RECONCILIATION_REQUIRED", broadcast.tx_hash, f"receipt verification unavailable: {exc}")
        if not isinstance(receipt, ReceiptEvidence):
            return SettlementResult("RECONCILIATION_REQUIRED", broadcast.tx_hash, "receipt evidence unavailable")
        if receipt.tx_hash.lower() != broadcast.tx_hash.lower():
            return SettlementResult("FAILED", broadcast.tx_hash, "receipt transaction hash mismatch")
        if receipt.chain_id != proposal.chain_id:
            return SettlementResult("FAILED", broadcast.tx_hash, "receipt chain mismatch")
        if receipt.proposal_digest != proposal.digest() or receipt.transaction_digest != tx.digest():
            return SettlementResult("FAILED", broadcast.tx_hash, "receipt does not bind to authorized proposal and transaction")
        if receipt.success is not True:
            return SettlementResult("FAILED", broadcast.tx_hash, "on-chain transaction reverted")
        if receipt.canonical is not True:
            return SettlementResult("RECONCILIATION_REQUIRED", broadcast.tx_hash, "receipt is non-canonical or reorg status unknown")
        if (not isinstance(receipt.confirmations, int) or isinstance(receipt.confirmations, bool)
                or not isinstance(receipt.required_confirmations, int)
                or isinstance(receipt.required_confirmations, bool)
                or receipt.required_confirmations < 1
                or receipt.confirmations < receipt.required_confirmations):
            return SettlementResult("BROADCAST", broadcast.tx_hash, "awaiting required confirmations")
        return SettlementResult("CONFIRMED", broadcast.tx_hash, "receipt verified and confirmation threshold met")
