'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { Policy } = require('../core/policy');
const { Validator } = require('../core/validator');
const { DurableState } = require('../state/store');
const { RouterAdapter, BoundTransaction } = require('../core/router-adapter');
const { SimulationBoundary } = require('../simulation/boundary');

function proposal(actor, transition) {
  const canonical = JSON.stringify({ actor, transition });
  return { actor, transition, hash: crypto.createHash('sha256').update(canonical).digest('hex') };
}

function journalPath() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'alpha-sentinel-'));
  return path.join(dir, 'lifecycle.journal');
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

test('durable journal survives restart and preserves audit chain', () => {
  const journal = journalPath();
  const validator = new Validator();
  const first = new DurableState({ ready: false }, { journalPath: journal });
  const t1 = validator.validate({
    state: first.snapshot(),
    transition: { type: 'set', expectedVersion: 0, payload: { key: 'ready', value: true } }
  });
  first.apply(t1);

  const second = new DurableState({ ready: false }, { journalPath: journal });
  assert.deepEqual(second.snapshot(), { version: 1, data: { ready: true } });
  assert.equal(second.audit().length, 1);
  assert.equal(second.audit()[0].previousHash, 'GENESIS');
  assert.match(second.audit()[0].recordHash, /^[a-f0-9]{64}$/);
});

test('tampered durable journal fails closed during recovery', () => {
  const journal = journalPath();
  const state = new DurableState({}, { journalPath: journal });
  const validated = new Validator().validate({
    state: state.snapshot(),
    transition: { type: 'set', expectedVersion: 0, payload: { key: 'x', value: 1 } }
  });
  state.apply(validated);

  const record = JSON.parse(fs.readFileSync(journal, 'utf8'));
  record.transition.payload.value = 999;
  fs.writeFileSync(journal, `${JSON.stringify(record)}\n`);

  assert.throws(() => new DurableState({}, { journalPath: journal }), /AUDIT_RECORD_HASH_INVALID/);
});

test('partial journal tail fails closed instead of silently recovering', () => {
  const journal = journalPath();
  fs.writeFileSync(journal, '{"sequence":1');
  assert.throws(() => new DurableState({}, { journalPath: journal }), /CORRUPT_JOURNAL_TRAILING_DATA/);
});
