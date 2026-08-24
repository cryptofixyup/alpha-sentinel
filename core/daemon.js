'use strict';

const { LifecycleCoordinator, STATES } = require('./lifecycle');

class AuthorizationDaemon {
  constructor({ policy, validator, state, routerAdapter, simulationBoundary }) {
    this.lifecycle = new LifecycleCoordinator({ policy, validator, state });
    if (!routerAdapter || typeof routerAdapter.construct !== 'function') throw new TypeError('routerAdapter required');
    if (!simulationBoundary || typeof simulationBoundary.simulate !== 'function') throw new TypeError('simulationBoundary required');
    this.routerAdapter = routerAdapter;
    this.simulationBoundary = simulationBoundary;
  }

  propose({ proposalId, proposalHash, payload }) {
    return this.lifecycle.propose({ proposalId, metadata: { proposalHash, payload } });
  }
  authorize({ actor }) { return this.lifecycle.advance({ actor, to: STATES.AUTHORIZED }); }
  validate({ actor }) { return this.lifecycle.advance({ actor, to: STATES.VALIDATED }); }
  enterTimelock({ actor, unlockAt }) {
    if (!Number.isInteger(unlockAt) || unlockAt < 0) throw new Error('INVALID_UNLOCK_TIME');
    return this.lifecycle.advance({ actor, to: STATES.TIMED_WAIT, metadata: { unlockAt } });
  }
  approve({ actor, now = Date.now() }) {
    const current = this.lifecycle.snapshot();
    if (current.lifecycle !== STATES.TIMED_WAIT) throw new Error(`INVALID_LIFECYCLE_TRANSITION:${current.lifecycle}->${STATES.APPROVED}`);
    if (!Number.isInteger(current.metadata.unlockAt)) throw new Error('TIMELOCK_NOT_CONFIGURED');
    if (now < current.metadata.unlockAt) throw new Error('TIMELOCK_ACTIVE');
    return this.lifecycle.advance({ actor, to: STATES.APPROVED, metadata: { approvedAt: now } });
  }

  bind({ actor }) {
    const current = this.lifecycle.snapshot();
    if (current.lifecycle !== STATES.APPROVED) throw new Error(`INVALID_LIFECYCLE_TRANSITION:${current.lifecycle}->${STATES.BOUND}`);
    const tx = this.routerAdapter.construct({
      actor,
      proposalId: current.proposalId,
      proposalHash: current.metadata.proposalHash,
      payload: current.metadata.payload,
    });
    this.lifecycle.advance({ actor, to: STATES.BOUND, metadata: { boundTransaction: tx } });
    return tx;
  }

  simulate({ actor }) {
    const current = this.lifecycle.snapshot();
    if (current.lifecycle !== STATES.BOUND) throw new Error(`INVALID_LIFECYCLE_TRANSITION:${current.lifecycle}->${STATES.SIMULATED}`);
    const tx = current.metadata.boundTransaction;
    const result = this.simulationBoundary.simulate(tx);
    this.lifecycle.advance({ actor, to: STATES.SIMULATED, metadata: { simulation: result } });
    return result;
  }

  execute({ actor }) { return this.lifecycle.advance({ actor, to: STATES.EXECUTED }); }
  verify({ actor }) { return this.lifecycle.advance({ actor, to: STATES.VERIFIED }); }
  snapshot() { return this.lifecycle.snapshot(); }
}

module.exports = { AuthorizationDaemon };
