import { STATES, transition } from './state.js';
import { validateTransition } from './validator.js';

export function validate({ current, proposal, to, policy }) {
  return validateTransition({ current, proposal, target: to, policy });
}

export function applyTransition({ current, proposal, to, policy }) {
  const validated = validate({ current, proposal, to, policy });
  return {
    ...validated,
    nextState: transition(current.state, to),
  };
}

export { STATES };
