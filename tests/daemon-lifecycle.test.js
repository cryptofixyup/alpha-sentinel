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

function daemon({ build, simulate } = {}) {
  const policy = new Policy(actor => actor === 'operator');
  const validator = new Validator();
  const state = new DurableState();
  const routerAdapter = new RouterAdapter({
    policy,
    validator,
    state,
    build: build || (({ proposalId, proposalHash, payload }) => ({ proposalId, proposalHash, payload })),
  });
  const simulationBoundary = new SimulationBoundary(simulate || (boundTransaction => ({ ok: true, proposalId: boundTransaction.proposalId })));
  return new AuthorizationDaemon({ policy, validator, state, routerAdapter, simulationBoundary });
}

function approve(d, proposalId, proposalHash = `hash-${proposalId}`) {
  d.propose({ proposalId, proposalHash, payload: { action: 'test' } });
  d.authorize({ actor: 'operator' });
  d.validate({ actor: 'operator' });
  d.enterTimelock({ actor: 'operator', unlockAt: 1 });
  d.approve({ actor: 'operator', now: 1 });
}

test('daemon uses one canonical durable lifecycle through router and simulation', () => {
  const d = daemon();
  approve(d, 'p-1');
  const bound = d.bind({ actor: 'operator' });
  assert.equal(bound.kind, 'BoundTransaction');
  assert.equal(bound.proposalId, 'p-1');
  assert.equal(bound.proposalHash, 'hash-p-1');
  assert.equal(d.snapshot().lifecycle, STATES.BOUND);
  const simulation = d.simulate({ actor: 'operator' });
  assert.equal(simulation.ok, true);
  assert.equal(d.snapshot().lifecycle, STATES.SIMULATED);
});

test('daemon cannot bypass lifecycle ordering', () => {
  const d = daemon();
  d.propose({ proposalId: 'p-2', proposalHash: 'hash-p-2', payload: {} });
  assert.throws(() => d.bind({ actor: 'operator' }), /INVALID_LIFECYCLE_TRANSITION/);
  assert.throws(() => d.simulate({ actor: 'operator' }), /INVALID_LIFECYCLE_TRANSITION/);
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

test('router binding rejects proposal identity or hash mismatch', () => {
  const d = daemon();
  approve(d, 'p-5');
  const adapter = d.routerAdapter;
  assert.throws(() => adapter.construct({ actor: 'operator', proposalId: 'wrong', proposalHash: 'hash-p-5', payload: {} }), /PROPOSAL_ID_MISMATCH/);
  assert.throws(() => adapter.construct({ actor: 'operator', proposalId: 'p-5', proposalHash: 'wrong-hash', payload: {} }), /PROPOSAL_HASH_MISMATCH/);
});

test('router binding rejects malformed transaction envelopes', () => {
  const d = daemon({ build: () => null });
  approve(d, 'p-6');
  assert.throws(() => d.bind({ actor: 'operator' }), /MALFORMED_TRANSACTION_ENVELOPE/);
});

test('failed simulation does not advance lifecycle', () => {
  const d = daemon({ simulate: () => ({ ok: false }) });
  approve(d, 'p-7');
  d.bind({ actor: 'operator' });
  assert.throws(() => d.simulate({ actor: 'operator' }), /SIMULATION_FAILED/);
  assert.equal(d.snapshot().lifecycle, STATES.BOUND);
});

test('simulation receives only a bound transaction', () => {
  const d = daemon({ simulate: boundTransaction => {
    assert.equal(boundTransaction.kind, 'BoundTransaction');
    assert.equal(boundTransaction.proposalId, 'p-8');
    assert.equal(boundTransaction.proposalHash, 'hash-p-8');
    return { ok: true, envelope: boundTransaction.payload };
  }});
  approve(d, 'p-8');
  d.bind({ actor: 'operator' });
  const result = d.simulate({ actor: 'operator' });
  assert.equal(result.ok, true);
  assert.equal(d.snapshot().lifecycle, STATES.SIMULATED);
});
