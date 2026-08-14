'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { Policy } = require('../core/policy');
const { Validator } = require('../core/validator');
const { DurableState } = require('../state/store');
const { AuthorizationDaemon } = require('../core/daemon');
const { RouterAdapter } = require('../core/router-adapter');
const { SimulationBoundary } = require('../simulation/boundary');
const { STATES } = require('../core/lifecycle');

function daemon() {
  const policy = new Policy(actor => actor === 'operator');
  const validator = new Validator();
  const state = new DurableState();
  const routerAdapter = new RouterAdapter({
    policy,
    validator,
    state,
    build: ({ proposalId, proposalHash, payload }) => ({
      proposalId,
      proposalHash,
      payload,
    }),
  });
  const simulationBoundary = new SimulationBoundary(boundTransaction => ({
    ok: true,
    proposalId: boundTransaction.proposalId,
  }));
  return new AuthorizationDaemon({ policy, validator, state, routerAdapter, simulationBoundary });
}

test('daemon uses one canonical durable lifecycle', () => {
  const d = daemon();
  d.propose({ proposalId: 'p-1', proposalHash: 'hash-p-1', payload: { action: 'test' } });
  d.authorize({ actor: 'operator' });
  d.validate({ actor: 'operator' });
  d.enterTimelock({ actor: 'operator', unlockAt: 1000 });

  assert.equal(d.snapshot().lifecycle, STATES.TIMED_WAIT);
  assert.throws(() => d.approve({ actor: 'operator', now: 999 }), /TIMELOCK_ACTIVE/);

  d.approve({ actor: 'operator', now: 1000 });
  const bound = d.bind({ actor: 'operator' });
  assert.equal(bound.kind, 'BoundTransaction');
  assert.equal(d.snapshot().lifecycle, STATES.BOUND);

  const simulation = d.simulate({ actor: 'operator' });
  assert.equal(simulation.ok, true);
  assert.equal(d.snapshot().lifecycle, STATES.SIMULATED);

  d.execute({ actor: 'operator' });
  d.verify({ actor: 'operator' });
  assert.equal(d.snapshot().lifecycle, STATES.VERIFIED);
});

test('daemon cannot bypass lifecycle ordering', () => {
  const d = daemon();
  d.propose({ proposalId: 'p-2', proposalHash: 'hash-p-2', payload: {} });
  assert.throws(() => d.approve({ actor: 'operator', now: Date.now() }), /INVALID_LIFECYCLE_TRANSITION/);
  assert.throws(() => d.execute({ actor: 'operator' }), /INVALID_LIFECYCLE_TRANSITION/);
});

test('daemon authorization remains policy-controlled', () => {
  const d = daemon();
  d.propose({ proposalId: 'p-3', proposalHash: 'hash-p-3', payload: {} });
  assert.throws(() => d.authorize({ actor: 'untrusted' }), /POLICY_DENIED/);
  assert.equal(d.snapshot().lifecycle, STATES.PROPOSED);
});

test('timelock cannot be skipped or approved before unlock', () => {
  const d = daemon();
  d.propose({ proposalId: 'p-4', proposalHash: 'hash-p-4', payload: {} });
  d.authorize({ actor: 'operator' });
  d.validate({ actor: 'operator' });
  assert.throws(() => d.approve({ actor: 'operator', now: 1000 }), /INVALID_LIFECYCLE_TRANSITION/);
  d.enterTimelock({ actor: 'operator', unlockAt: 2000 });
  assert.throws(() => d.approve({ actor: 'operator', now: 1999 }), /TIMELOCK_ACTIVE/);
});

test('failed simulation does not advance lifecycle', () => {
  const policy = new Policy(actor => actor === 'operator');
  const validator = new Validator();
  const state = new DurableState();
  const routerAdapter = new RouterAdapter({
    policy,
    validator,
    state,
    build: () => ({ to: 'router', data: '0x' }),
  });
  const simulationBoundary = new SimulationBoundary(() => ({ ok: false }));
  const d = new AuthorizationDaemon({ policy, validator, state, routerAdapter, simulationBoundary });

  d.propose({ proposalId: 'p-5', proposalHash: 'hash-p-5', payload: {} });
  d.authorize({ actor: 'operator' });
  d.validate({ actor: 'operator' });
  d.enterTimelock({ actor: 'operator', unlockAt: 1 });
  d.approve({ actor: 'operator', now: 1 });
  d.bind({ actor: 'operator' });

  assert.throws(() => d.simulate({ actor: 'operator' }), /SIMULATION_FAILED/);
  assert.equal(d.snapshot().lifecycle, STATES.BOUND);
});
