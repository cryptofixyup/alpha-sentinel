'use strict';

const { LifecycleCoordinator, STATES } = require('./lifecycle');

/**
 * Deterministic daemon facade over the canonical lifecycle.
 *
 * This is intentionally not a second state machine: every lifecycle mutation is
 * delegated to LifecycleCoordinator -> Policy -> Validator -> DurableState.
 */
class AuthorizationDaemon {
  constructor({ policy, validator, state }) {
    this.lifecycle = new LifecycleCoordinator({ policy, validator, state });
  }

  propose({ proposalId }) {
    return this.lifecycle.propose({ proposalId });
  }

  authorize({ actor }) {
    return this.lifecycle.advance({ actor, to: STATES.AUTHORIZED });
  }

  validate({ actor }) {
    return this.lifecycle.advance({ actor, to: STATES.VALIDATED });
  }

  enterTimelock({ actor, unlockAt }) {
    if (!Number.isInteger(unlockAt) || unlockAt < 0) throw new Error('INVALID_UNLOCK_TIME');
    return this.lifecycle.advance({
      actor,
      to: STATES.TIMED_WAIT,
      metadata: { unlockAt },
    });
  }

  approve({ actor, now = Date.now() }) {
    const current = this.lifecycle.snapshot();
    const unlockAt = current.metadata.unlockAt;
    if (!Number.isInteger(unlockAt)) throw new Error('TIMELOCK_NOT_CONFIGURED');
    if (now < unlockAt) throw new Error('TIMELOCK_ACTIVE');
    return this.lifecycle.advance({ actor, to: STATES.APPROVED, metadata: { approvedAt: now } });
  }

  bind({ actor }) {
    return this.lifecycle.advance({ actor, to: STATES.BOUND });
  }

  simulate({ actor }) {
    return this.lifecycle.advance({ actor, to: STATES.SIMULATED });
  }

  execute({ actor }) {
    return this.lifecycle.advance({ actor, to: STATES.EXECUTED });
  }

  verify({ actor }) {
    return this.lifecycle.advance({ actor, to: STATES.VERIFIED });
  }

  snapshot() {
    return this.lifecycle.snapshot();
  }
}

module.exports = { AuthorizationDaemon };
