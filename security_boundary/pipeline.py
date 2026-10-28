from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
import time
from typing import Callable

from .approval import Approval, Timelock, validate_approval
from .execution import SignedTransaction
from .execution_controls import ExecutionGate, MarketEvidence
from .execution_state import SQLiteExecutionState
from .models import ProposalStatus, TradeIntent, TradeProposal, TransactionEnvelope
from .policy import Policy
from .proposal import make_proposal
from .risk import RiskEngine
from .router import RouterAdapter, validate_built_transaction
from .signer import IsolatedSigner
from .simulation import ChainSimulator, SimulationResult, simulate
from .store import ProposalStore


ApprovalProvider = Callable[[TradeProposal, TransactionEnvelope, SimulationResult], Approval | None]


@dataclass(frozen=True)
class PipelineResult:
    status: ProposalStatus
    proposal: TradeProposal | None
    transaction: TransactionEnvelope | None
    simulation: SimulationResult | None
    signed_transaction: SignedTransaction | None
    reason: str


class BoundaryPipeline:
    """Strict one-way trust pipeline. No LLM object is accepted here."""

    def __init__(
        self,
        risk: RiskEngine,
        policy: Policy,
        router: RouterAdapter,
        simulator: ChainSimulator,
        signer: IsolatedSigner,
        timelock: Timelock | None = None,
        approval_provider: ApprovalProvider | None = None,
        proposal_store: ProposalStore | None = None,
        execution_gate: ExecutionGate | None = None,
        execution_state: SQLiteExecutionState | None = None,
    ) -> None:
        self.risk = risk
        self.policy = policy
        self.router = router
        self.simulator = simulator
        self.signer = signer
        self.timelock = timelock or Timelock()
        self.approval_provider = approval_provider
        self.proposal_store = proposal_store or ProposalStore()
        self.execution_gate = execution_gate
        self.execution_state = execution_state

        # Production requires mandatory evidence gates and durable state for both
        # proposal/signing idempotency and shared exposure reservations.
        if os.environ.get("ALPHA_SENTINEL_ENV", "").strip().lower() == "production":
            if execution_gate is None:
                raise RuntimeError("production requires an explicitly configured ExecutionGate")
            if execution_state is None or not execution_state.is_persistent:
                raise RuntimeError("production requires persistent shared execution-state storage")
            if not self.proposal_store.is_persistent:
                raise RuntimeError("production requires persistent proposal storage")

    def execute(
        self,
        intent: TradeIntent,
        portfolio_exposure_bps: int,
        *, request_id: str | None = None,
        market_evidence: MarketEvidence | dict[str, object] | None = None,
    ) -> PipelineResult:
        # 0. Optional explicitly configured production execution gate. If enabled,
        # missing or invalid market evidence rejects before touching the simulator.
        if self.execution_gate is not None:
            try:
                self.execution_gate.evaluate(market_evidence)
            except Exception as exc:
                return PipelineResult(ProposalStatus.POLICY_REJECTED, None, None, None, None, str(exc))

        # 1. RISK
        gas_gwei = self.simulator.gas_price() // 1_000_000_000
        risk = self.risk.evaluate(intent.size_bps, portfolio_exposure_bps, gas_gwei)
        if not risk.allowed:
            return PipelineResult(
                ProposalStatus.POLICY_REJECTED, None, None, None, None, risk.reason
            )

        # 2. POLICY
        try:
            self.policy.authorize(intent, risk)
        except PermissionError as exc:
            return PipelineResult(
                ProposalStatus.POLICY_REJECTED, None, None, None, None, str(exc)
            )

        # 3. PROPOSAL + 4. HASH
        fingerprint = hashlib.sha256(json.dumps({
            "intent": asdict(intent), "policy": asdict(self.policy),
            "limits": asdict(self.risk.limits),
            "timelock": [self.timelock.threshold_bps, self.timelock.duration_seconds],
        }, sort_keys=True).encode()).hexdigest()
        request_id = fingerprint if request_id is None else request_id
        if not isinstance(request_id, str) or not request_id.strip():
            return PipelineResult(ProposalStatus.FAILED, None, None, None, None, "request identity required")
        try:
            saved = self.proposal_store.get(request_id, fingerprint)
        except Exception as exc:
            return PipelineResult(ProposalStatus.FAILED, None, None, None, None, str(exc))
        proposal = saved[0] if saved else make_proposal(
            intent,
            self.policy,
            risk.risk_score_bps,
            self.risk.limits.max_slippage_bps,
            self.risk.limits.max_gas_price_gwei * 1_000_000_000,
            deadline_seconds=300 + (self.timelock.duration_seconds if intent.size_bps > self.timelock.threshold_bps else 0),
        )
        if saved and saved[2]:
            return PipelineResult(ProposalStatus.SIGNING_BLOCKED, proposal, saved[1], None, None, "signing already attempted; reconciliation required")
        if int(time.time()) >= proposal.deadline:
            return PipelineResult(ProposalStatus.FAILED, proposal, None, None, None, "proposal expired")

        # 5. ROUTER-SPECIFIC TRANSACTION BUILDER
        try:
            tx = saved[1] if saved else self.router.build(proposal)
            validate_built_transaction(proposal, tx)
            if not saved:
                proposal, tx, attempted = self.proposal_store.save(request_id, fingerprint, proposal, tx)
                if attempted:
                    raise RuntimeError("signing already attempted; reconciliation required")
                validate_built_transaction(proposal, tx)
        except Exception as exc:
            return PipelineResult(
                ProposalStatus.FAILED, proposal, None, None, None,
                f"transaction build blocked: {exc}",
            )

        # 6. SIMULATION
        if int(time.time()) >= proposal.deadline:
            return PipelineResult(ProposalStatus.FAILED, proposal, tx, None, None, "proposal expired")
        simulation = simulate(proposal, tx, self.simulator)
        if not simulation.passed:
            return PipelineResult(
                ProposalStatus.SIMULATION_FAILED,
                proposal, tx, simulation, None, simulation.reason,
            )

        # 7. TIMELOCK / APPROVAL
        if not self.timelock.ready(proposal.proposal_id, proposal.size_bps, proposal.created_at):
            return PipelineResult(
                ProposalStatus.TIMELOCKED,
                proposal, tx, simulation, None,
                "timelock not expired",
            )

        # Re-simulate after timelock before approval/signing.
        if int(time.time()) >= proposal.deadline:
            return PipelineResult(ProposalStatus.FAILED, proposal, tx, simulation, None, "proposal expired")
        simulation = simulate(proposal, tx, self.simulator)
        if not simulation.passed:
            return PipelineResult(
                ProposalStatus.SIMULATION_FAILED,
                proposal, tx, simulation, None,
                "post-timelock simulation failed: " + simulation.reason,
            )

        if self.approval_provider is None:
            return PipelineResult(
                ProposalStatus.SIGNING_BLOCKED,
                proposal, tx, simulation, None,
                "approval provider not configured",
            )

        try:
            approval = self.approval_provider(proposal, tx, simulation)
            if approval is None:
                raise PermissionError("approval not granted")
            validate_approval(proposal, tx, approval)
        except Exception as exc:
            return PipelineResult(
                ProposalStatus.SIGNING_BLOCKED,
                proposal, tx, simulation, None, str(exc),
            )

        # 8. Reserve portfolio capacity atomically immediately before signing.
        # Every production worker must share the same transactional state database.
        portfolio_id = f"{self.policy.chain_id}:{self.policy.wallet}"
        reservation_acquired = False
        if self.execution_state is not None:
            try:
                self.execution_state.reserve_exposure(
                    portfolio_id,
                    proposal.proposal_id,
                    risk.permitted_size_bps,
                    portfolio_exposure_bps,
                    self.risk.limits.max_portfolio_exposure_bps,
                )
                reservation_acquired = True
            except Exception as exc:
                return PipelineResult(
                    ProposalStatus.POLICY_REJECTED,
                    proposal, tx, simulation, None,
                    f"atomic exposure reservation blocked: {exc}",
                )

        # 9. ISOLATED SIGNER. Never release a reservation merely because another
        # worker lost the signing claim; that worker may own the same reservation.
        signing_claimed = False
        try:
            if int(time.time()) >= proposal.deadline:
                raise PermissionError("proposal expired before signing")
            if not self.proposal_store.claim_signing(request_id):
                raise PermissionError("signing already attempted; reconciliation required")
            signing_claimed = True
            signed = self.signer.sign(proposal, tx, approval)
            signed.validate(proposal, tx)
        except Exception as exc:
            if reservation_acquired and signing_claimed:
                try:
                    self.execution_state.release_exposure(portfolio_id, proposal.proposal_id)
                except Exception as release_exc:
                    exc = RuntimeError(f"{exc}; exposure reservation release failed: {release_exc}")
            return PipelineResult(
                ProposalStatus.SIGNING_BLOCKED,
                proposal, tx, simulation, None, str(exc),
            )

        # 10. BROADCAST and 11. VERIFICATION intentionally remain outside
        # this process. The signer returns an authorization-bound opaque payload.
        return PipelineResult(
            ProposalStatus.SIGNED,
            proposal,
            tx,
            simulation,
            signed,
            "signed by isolated signer; broadcast/verification pending",
        )
