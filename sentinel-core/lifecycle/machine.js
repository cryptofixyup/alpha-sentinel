import { STATES, transition } from './state.js';

export function applyTransition({ current, proposal, to }) {
  if (current.version !== proposal.expectedVersion) throw new Error('STALE_PROPOSAL');
  if (current.proposalId !== null && current.proposalId === proposal.id) throw new Error('DUPLICATE_PROPOSAL');
  if (current.actor !== proposal.actor) throw new Error('UNAUTHORIZED_ACTOR');
  const nextState = transition(current.state, to);
  return { ...current, state: nextState, version: current.version + 1, proposalId: proposal.id };
}

export { STATES };
