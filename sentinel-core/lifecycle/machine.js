import { STATES, transition } from './state.js';
import { validateTransition } from './validator.js';

export function applyTransition({ current, proposal, to, policy }) {
  validateTransition({ current, proposal, target: to, policy });
  const nextState = transition(current.state, to);
  return { ...current, state: nextState, version: current.version + 1, proposalId: proposal.id };
}

export { STATES };
