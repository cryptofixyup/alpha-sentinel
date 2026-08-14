import { DECISIONS, authorize } from '../policy/policy.js';
import { canTransition } from './state.js';

const VALIDATED = Symbol('ValidatedTransition');

export function validateTransition({ current, proposal, target, policy }) {
  const decision = authorize({ proposal, state: current, policy });
  return validate({ proposal, state: current, policyDecision: decision, target });
}

// Canonical validator entry point. Authorization remains an explicit
// precondition and is never delegated to DurableState.
export function validate({ proposal, state, policyDecision, target }) {
  if (policyDecision !== DECISIONS.ALLOW) throw new Error('POLICY_DENIED');

  const currentState = state?.state?.state ?? state?.state;
  if (!canTransition(currentState, target)) {
    throw new Error(`INVALID_TRANSITION:${currentState}->${target}`);
  }
  if (proposal.expectedVersion !== state.version) {
    throw new Error('STALE_PROPOSAL_VERSION');
  }

  const transitionId = `${proposal.id}:${state.version}:${target}`;

  return Object.freeze({
    [VALIDATED]: true,
    transitionId,
    proposalId: proposal.id,
    fromVersion: state.version,
    fromState: currentState,
    target,
  });
}

export function isValidatedTransition(value) {
  return Boolean(value?.[VALIDATED] === true);
}
