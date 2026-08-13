import pytest

from alpha_sentinel.transaction import (
    LifecycleState, PipelineViolation, Proposal, TransactionIntent,
    approve, audit_event, bind_transaction, transition, verify_audit_chain,
)


def make_bound():
    proposal = Proposal("p-1", "router-a", {"method": "swap", "amount": 10})
    intent = TransactionIntent(proposal.proposal_hash, "1", 7, "0xabc", 10, b"payload")
    return proposal, bind_transaction(intent, "sim-commitment")


def test_binding_is_deterministic_and_immutable():
    proposal, bound = make_bound()
    assert bound.intent.proposal_hash == proposal.proposal_hash
    with pytest.raises(AttributeError):
        bound.binding_hash = "tampered"


def test_approval_requires_exact_proposal_binding():
    _, bound = make_bound()
    approval = approve(bound, bound.intent.proposal_hash, "operator-1")
    assert approval.binding_hash == bound.binding_hash
    with pytest.raises(PipelineViolation):
        approve(bound, "wrong-proposal", "operator-1")


def test_illegal_transition_fails_closed():
    with pytest.raises(PipelineViolation):
        transition(LifecycleState.PROPOSED, LifecycleState.SIGNED, subject_hash="x")


def test_audit_chain_detects_tampering():
    first = audit_event(LifecycleState.PROPOSED, "p")
    second = transition(LifecycleState.PROPOSED, LifecycleState.SIMULATED, subject_hash="p", previous_audit_hash=first.event_hash)
    verify_audit_chain((first, second))
    tampered = audit_event(LifecycleState.APPROVED, "p", first.event_hash)
    with pytest.raises(PipelineViolation):
        verify_audit_chain((first, tampered))
