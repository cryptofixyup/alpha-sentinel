import { DECISIONS, authorize } from '../policy/policy.js';
import { canTransition } from './state.js';

const VALIDATED = Symbol('ValidatedTransition');

export function validateTransition({ current, proposal, target, policy }) {
  const decision = authorize({ proposal, state: current, policy });
  if (decision !== DECISIONS.ALLOW) throw new Error('POLICY_DENIED');
  if (current.proposalId === proposal.id) throw new Error('DUPLICATE_PROPOSAL');
  if (!canTransition(current.state, target)) {
    throw new Error(`INVALID_TRANSITION:${current.state}->${target}`);
  }

  return Object.freeze({
    [VALIDATED]: true,
    proposalId: proposal.id,
    fromVersion: current.version,
    fromState: current.state,
    target,
  });
}

export function isValidatedTransition(value) {
  return Boolean(value?.[VALIDATED] === true);
}
