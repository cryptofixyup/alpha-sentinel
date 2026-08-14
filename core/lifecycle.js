'use strict';

/**
 * Canonical proposal lifecycle orchestration.
 *
 * This module owns lifecycle transition rules only. DurableState remains the sole
 * mutation authority; Policy remains the sole authorization boundary.
 */
const STATES = Object.freeze({
  PROPOSED: 'PROPOSED',
  AUTHORIZED: 'AUTHORIZED',
  VALIDATED: 'VALIDATED',
  TIMED_WAIT: 'TIMED_WAIT',
  APPROVED: 'APPROVED',
  BOUND: 'BOUND',
  SIMULATED: 'SIMULATED',
  EXECUTED: 'EXECUTED',
  VERIFIED: 'VERIFIED',
});

const TRANSITIONS = Object.freeze({
  [STATES.PROPOSED]: [STATES.AUTHORIZED],
  [STATES.AUTHORIZED]: [STATES.VALIDATED],
  [STATES.VALIDATED]: [STATES.TIMED_WAIT],
  [STATES.TIMED_WAIT]: [STATES.APPROVED],
  [STATES.APPROVED]: [STATES.BOUND],
  [STATES.BOUND]: [STATES.SIMULATED],
  [STATES.SIMULATED]: [STATES.EXECUTED],
  [STATES.EXECUTED]: [STATES.VERIFIED],
});

class LifecycleCoordinator {
  constructor({ policy, validator, state }) {
    if (!policy || typeof policy.authorize !== 'function') throw new TypeError('policy required');
    if (!validator || typeof validator.validate !== 'function') throw new TypeError('validator required');
    if (!state || typeof state.snapshot !== 'function' || typeof state.apply !== 'function') {
      throw new TypeError('durable state required');
    }
    this.policy = policy;
    this.validator = validator;
    this.state = state;
  }

  snapshot() {
    const snapshot = this.state.snapshot();
    const lifecycle = snapshot.data.lifecycle ?? { state: STATES.PROPOSED, proposalId: null };
    return Object.freeze({
      version: snapshot.version,
      lifecycle: lifecycle.state,
      proposalId: lifecycle.proposalId ?? null,
      metadata: structuredClone(lifecycle.metadata ?? {}),
    });
  }

  propose({ proposalId }) {
    if (!proposalId || typeof proposalId !== 'string') throw new Error('INVALID_PROPOSAL_ID');
    const current = this.state.snapshot();
    if (current.data.lifecycle) throw new Error('PROPOSAL_ALREADY_EXISTS');

    return this._applyTransition(null, STATES.PROPOSED, {
      proposalId,
      metadata: {},
    }, { authorize: false });
  }

  advance({ actor, to, metadata = {} }) {
    const current = this.snapshot();
    if (!Object.values(STATES).includes(to)) throw new Error('INVALID_LIFECYCLE_STATE');
    if (!(TRANSITIONS[current.lifecycle] || []).includes(to)) {
      throw new Error(`INVALID_LIFECYCLE_TRANSITION:${current.lifecycle}->${to}`);
    }

    return this._applyTransition(current.lifecycle, to, {
      proposalId: current.proposalId,
      metadata,
    }, { actor, authorize: true });
  }

  _applyTransition(expectedState, nextState, lifecycle, { actor, authorize }) {
    const snapshot = this.state.snapshot();
    const current = snapshot.data.lifecycle ?? { state: STATES.PROPOSED, proposalId: null };
    if (expectedState !== null && current.state !== expectedState) {
      throw new Error('LIFECYCLE_STATE_CONFLICT');
    }
    if (expectedState === null && snapshot.data.lifecycle) {
      throw new Error('PROPOSAL_ALREADY_EXISTS');
    }

    const transition = {
      type: 'set',
      expectedVersion: snapshot.version,
      payload: {
        key: 'lifecycle',
        value: Object.freeze({
          state: nextState,
          proposalId: lifecycle.proposalId,
          metadata: structuredClone(lifecycle.metadata ?? {}),
        }),
      },
    };

    let authorizedActor = null;
    if (authorize) {
      const authorized = this.policy.authorize({ actor, transition: {
        type: 'lifecycle',
        from: expectedState,
        to: nextState,
        proposalId: lifecycle.proposalId,
        metadata: lifecycle.metadata,
      }});
      authorizedActor = authorized.actor;
    }

    const validated = this.validator.validate({ state: snapshot, transition });
    this.state.apply(validated);
    return Object.freeze({
      lifecycle: nextState,
      proposalId: lifecycle.proposalId,
      actor: authorizedActor,
      version: this.state.version,
    });
  }
}

module.exports = { LifecycleCoordinator, STATES, TRANSITIONS };
