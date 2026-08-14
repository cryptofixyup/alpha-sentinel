import { DECISIONS, authorize } from '../policy/policy.js';
import { canTransition } from './state.js';

export function validateTransition({ current, proposal, target, policy }) {
  const decision = authorize({ proposal, state: current, policy });
  if (decision !== DECISIONS.ALLOW) throw new Error('POLICY_DENIED');
  if (current.proposalId === proposal.id) throw new Error('DUPLICATE_PROPOSAL');
  if (!canTransition(current.state, target)) throw new Error(`INVALID_TRANSITION:${current.state}->${target}`);
  return true;
}
