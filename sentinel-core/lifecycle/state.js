export const STATES = Object.freeze({ PROPOSED: 'PROPOSED', VALIDATED: 'VALIDATED', APPROVED: 'APPROVED', EXECUTING: 'EXECUTING', COMPLETED: 'COMPLETED', REJECTED: 'REJECTED', FAILED: 'FAILED' });

const TRANSITIONS = Object.freeze({
  PROPOSED: Object.freeze(['VALIDATED', 'REJECTED']),
  VALIDATED: Object.freeze(['APPROVED', 'REJECTED']),
  APPROVED: Object.freeze(['EXECUTING', 'REJECTED']),
  EXECUTING: Object.freeze(['COMPLETED', 'FAILED']),
  COMPLETED: Object.freeze([]), REJECTED: Object.freeze([]), FAILED: Object.freeze([])
});

export function isValidState(state) { return Object.hasOwn(STATES, state); }
export function canTransition(from, to) { return TRANSITIONS[from]?.includes(to) ?? false; }
export function transition(from, to) {
  if (!isValidState(from) || !isValidState(to) || !canTransition(from, to)) throw new Error(`INVALID_TRANSITION:${from}->${to}`);
  return to;
}
export function permittedTransitions(from) { return Object.freeze([...(TRANSITIONS[from] ?? [])]); }
