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

function validateProposal(d, proposalId, proposalHash = `hash-${proposalId}`) {
  d.propose({ proposalId, proposalHash, payload: { action: 'test' } });
  d.authorize({ actor: 'operator' });
  d.validate({ actor: 'operator' });
}

test('daemon uses one canonical durable lifecycle through router and simulation', () => {
  const d = daemon();
  validateProposal(d, 'p-1');
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
  d.bind({ actor: 'operator' });
  d.simulate({ actor: 'operator' });
  d.enterTimelock({ actor: 'operator', unlockAt: 2000 });
  assert.throws(() => d.resimulate({ actor: 'operator', now: 1999 }), /TIMELOCK_ACTIVE/);
});

test('router binding rejects proposal identity or hash mismatch', () => {
  const d = daemon();
  validateProposal(d, 'p-5');
  const adapter = d.routerAdapter;
  assert.throws(() => adapter.construct({ actor: 'operator', proposalId: 'wrong', proposalHash: 'hash-p-5', payload: {} }), /PROPOSAL_ID_MISMATCH/);
  assert.throws(() => adapter.construct({ actor: 'operator', proposalId: 'p-5', proposalHash: 'wrong-hash', payload: {} }), /PROPOSAL_HASH_MISMATCH/);
});

test('router binding rejects malformed transaction envelopes', () => {
  const d = daemon({ build: () => null });
  validateProposal(d, 'p-6');
  assert.throws(() => d.bind({ actor: 'operator' }), /MALFORMED_TRANSACTION_ENVELOPE/);
});

test('failed simulation does not advance lifecycle', () => {
  const d = daemon({ simulate: () => ({ ok: false }) });
  validateProposal(d, 'p-7');
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
  validateProposal(d, 'p-8');
  d.bind({ actor: 'operator' });
  const result = d.simulate({ actor: 'operator' });
  assert.equal(result.ok, true);
  assert.equal(d.snapshot().lifecycle, STATES.SIMULATED);
});

test('classified agent and model principals are rejected before a permissive callback', () => {
  let callbackCalls = 0;
  const policy = new Policy(() => { callbackCalls++; return true; });
  const state = new DurableState();
  const d = new AuthorizationDaemon({ policy, validator: new Validator(), state,
    routerAdapter: { construct: () => ({}) },
    simulationBoundary: { simulate: () => ({ ok: true }) } });
  d.propose({ proposalId: 'agent-denied', proposalHash: 'hash', payload: {} });
  const before = state.snapshot();
  for (const kind of ['agent', 'model']) {
    assert.throws(() => d.authorize({ actor: { kind, id: 'untrusted' } }), /POLICY_DENIED/);
  }
  assert.equal(callbackCalls, 0);
  assert.deepEqual(state.snapshot(), before);
  assert.equal(d.snapshot().lifecycle, STATES.PROPOSED);
});

test('operator objects and legacy strings remain subject to callback authorization', () => {
  const operator = { kind: 'operator', id: 'trusted' };
  const policy = new Policy(actor => actor === operator || actor === 'operator');
  assert.equal(policy.authorize({ actor: operator, transition: {} }).actor, operator);
  assert.equal(policy.authorize({ actor: 'operator', transition: {} }).actor, 'operator');
  assert.throws(() => policy.authorize({ actor: { kind: 'operator', id: 'other' }, transition: {} }), /POLICY_DENIED/);
  assert.throws(() => policy.authorize({ actor: 'untrusted', transition: {} }), /POLICY_DENIED/);
});

test('policy requires explicit synchronous true before advancing durable lifecycle', () => {
  const invalidDecisions = [undefined, null, false, 0, 1, '', 'allow', {}, [],
    new Boolean(false), Promise.resolve(false), Promise.resolve(true)];
  for (const decision of invalidDecisions) {
    const policy = new Policy(() => decision);
    const state = new DurableState();
    const daemon = new AuthorizationDaemon({ policy, validator: new Validator(), state,
      routerAdapter: { construct: () => ({}) },
      simulationBoundary: { simulate: () => ({ ok: true }) } });
    daemon.propose({ proposalId: 'explicit-authorization', proposalHash: 'hash', payload: {} });
    const before = state.snapshot();
    assert.throws(() => daemon.authorize({ actor: 'operator' }), /POLICY_DENIED/);
    assert.deepEqual(state.snapshot(), before);
    assert.equal(daemon.snapshot().lifecycle, STATES.PROPOSED);
  }
  assert.equal(new Policy(() => true).authorize({ actor: 'operator', transition: {} }).actor,
    'operator');
});
