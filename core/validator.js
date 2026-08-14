'use strict';

/** Deterministic transition validation. Authorization is intentionally absent. */
class Validator {
  validate({ state, transition }) {
    if (!transition || typeof transition !== 'object') throw new Error('INVALID_TRANSITION');
    if (!transition.type) throw new Error('INVALID_TRANSITION_TYPE');
    if (transition.expectedVersion !== state.version) throw new Error('VERSION_CONFLICT');
    return Object.freeze({
      kind: 'ValidatedTransition',
      type: transition.type,
      payload: structuredClone(transition.payload ?? {}),
      expectedVersion: state.version,
    });
  }
}

module.exports = { Validator };
