from __future__ import annotations

from dataclasses import dataclass

from .approval import Timelock
from .models import ProposalStatus, RiskDecision, TradeIntent, TradeProposal, TransactionEnvelope
from .policy import Policy
from .proposal import make_proposal
from .risk import RiskEngine
from .router import RouterAdapter
from .signer import IsolatedSigner
from .simulation import ChainSimulator, SimulationResult, simulate


@dataclass(frozen=True)
class PipelineResult:
    status: ProposalStatus
    proposal: TradeProposal | None
    transaction: TransactionEnvelope | None
    simulation: SimulationResult | None
    signed_transaction: str | None
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
    ) -> None:
        self.risk = risk
        self.policy = policy
        self.router = router
        self.simulator = simulator
        self.signer = signer
        self.timelock = timelock or Timelock()

    def execute(
        self,
        intent: TradeIntent,
        portfolio_exposure_bps: int,
    ) -> PipelineResult:
        # 1. RISK
        gas_gwei = self.simulator.gas_price() // 1_000_000_000
        risk = self.risk.evaluate(
            intent.size_bps,
            portfolio_exposure_bps,
            gas_gwei,
        )
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
        proposal = make_proposal(
            intent,
            self.policy,
            risk.risk_score_bps,
            self.risk.limits.max_slippage_bps,
            self.risk.limits.max_gas_price_gwei * 1_000_000_000,
        )
        proposal_digest = proposal.digest()

        # 5. ROUTER-SPECIFIC TRANSACTION BUILDER
        try:
            tx = self.router.build(proposal)
        except Exception as exc:
            return PipelineResult(
                ProposalStatus.FAILED, proposal, None, None, None,
                f"transaction build blocked: {exc}",
            )

        if tx.proposal_digest != proposal_digest:
            return PipelineResult(
                ProposalStatus.FAILED, proposal, tx, None, None,
                "transaction/proposal digest mismatch",
            )

        # 6. SIMULATION
        simulation = simulate(proposal, tx, self.simulator)
        if not simulation.passed:
            return PipelineResult(
                ProposalStatus.SIMULATION_FAILED,
                proposal, tx, simulation, None, simulation.reason,
            )

        # 7. TIMELOCK / APPROVAL
        if not self.timelock.ready(proposal.proposal_id, proposal.size_bps):
            return PipelineResult(
                ProposalStatus.TIMELOCKED,
                proposal, tx, simulation, None,
                "timelock not expired",
            )

        # Re-simulate after timelock before signing.
        simulation = simulate(proposal, tx, self.simulator)
        if not simulation.passed:
            return PipelineResult(
                ProposalStatus.SIMULATION_FAILED,
                proposal, tx, simulation, None,
                "post-timelock simulation failed: " + simulation.reason,
            )

        # 8. ISOLATED SIGNER
        try:
            signed = self.signer.sign(proposal, tx)
        except Exception as exc:
            return PipelineResult(
                ProposalStatus.SIGNING_BLOCKED,
                proposal, tx, simulation, None, str(exc),
            )

        # 9. BROADCAST and 10. VERIFICATION intentionally remain outside
        # this process. The signer returns an opaque signed transaction.
        return PipelineResult(
            ProposalStatus.SIGNED,
            proposal,
            tx,
            simulation,
            signed,
            "signed by isolated signer; broadcast/verification pending",
        )
