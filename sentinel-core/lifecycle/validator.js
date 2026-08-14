import { DECISIONS, authorize } from '../policy/policy.js';
import { canTransition } from './state.js';

const VALIDATED = Symbol('ValidatedTransition');

export function validateTransition({ current, proposal, target, policy }) {
  const decision = authorize({ proposal, state: current, policy });
  if (decision !== DECISIONS.ALLOW) throw new Error('POLICY_DENIED');
  if (!canTransition(current.state, target)) {
    throw new Error(`INVALID_TRANSITION:${current.state}->${target}`);
  }
  if (proposal.expectedVersion !== current.version) {
    throw new Error('STALE_PROPOSAL_VERSION');
  }

  // A proposal identifies the lifecycle object. Each committed transition is
  // identified separately by source version and target state. This permits
  // one proposal to advance through multiple durable lifecycle states while
  // making replay of the exact validated transition fail closed.
  const transitionId = `${proposal.id}:${current.version}:${target}`;

  return Object.freeze({
    [VALIDATED]: true,
    transitionId,
    proposalId: proposal.id,
    fromVersion: current.version,
    fromState: current.state,
    target,
  });
}

export function isValidatedTransition(value) {
  return Boolean(value?.[VALIDATED] === true);
}
