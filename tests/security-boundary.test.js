'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { Policy } = require('../core/policy');
const { Validator } = require('../core/validator');
const { DurableState } = require('../state/store');
const { RouterAdapter, BoundTransaction } = require('../core/router-adapter');
const { SimulationBoundary } = require('../simulation/boundary');

function proposal(actor, transition) {
  const canonical = JSON.stringify({ actor, transition });
  return { actor, transition, hash: crypto.createHash('sha256').update(canonical).digest('hex') };
}

test('authorized proposal becomes a BoundTransaction', () => {
  const state = new DurableState({ ready: false });
  const policy = new Policy(actor => actor === 'operator');
  const adapter = new RouterAdapter({ policy, validator: new Validator(), state });
  const tx = adapter.construct(proposal('operator', {
    type: 'set', expectedVersion: 0, payload: { key: 'ready', value: true }
  }));
  assert.ok(tx instanceof BoundTransaction);
  assert.equal(tx.kind, 'BoundTransaction');
});

test('unauthorized actor is rejected before state mutation', () => {
  const state = new DurableState({ ready: false });
  const adapter = new RouterAdapter({ policy: new Policy(() => false), validator: new Validator(), state });
  assert.throws(() => adapter.construct(proposal('agent', {
    type: 'set', expectedVersion: 0, payload: { key: 'ready', value: true }
  })), /POLICY_DENIED/);
  assert.deepEqual(state.snapshot().data, { ready: false });
});

test('DurableState rejects raw transitions and has no actor authorization path', () => {
  const state = new DurableState();
  assert.throws(() => state.apply({ type: 'set', payload: {} }), /VALIDATED_TRANSITION_REQUIRED/);
  assert.equal(Object.prototype.hasOwnProperty.call(state, 'authorize'), false);
});

test('simulation accepts only BoundTransaction', () => {
  const simulation = new SimulationBoundary();
  assert.throws(() => simulation.simulate({ kind: 'ValidatedTransition' }), /BOUND_TRANSACTION_REQUIRED/);
});

test('validated transition is the only mutation input', () => {
  const state = new DurableState();
  const validated = new Validator().validate({
    state: state.snapshot(),
    transition: { type: 'set', expectedVersion: 0, payload: { key: 'x', value: 1 } }
  });
  assert.equal(state.apply(validated).data.x, 1);
});
