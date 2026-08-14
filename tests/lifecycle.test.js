'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { Policy } = require('../core/policy');
const { Validator } = require('../core/validator');
const { DurableState } = require('../state/store');
const { LifecycleCoordinator, STATES } = require('../core/lifecycle');

function makeCoordinator(authorizer = () => true, initial = {}) {
  const journalPath = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'alpha-lifecycle-')), 'journal');
  const state = new DurableState(initial, { journalPath });
  const coordinator = new LifecycleCoordinator({
    policy: new Policy(authorizer),
    validator: new Validator(),
    state,
  });
  return { coordinator, state, journalPath };
}

test('proposal creation is durable and starts at PROPOSED', () => {
  const { coordinator, state } = makeCoordinator();
  const result = coordinator.propose({ proposalId: 'p-1' });
  assert.equal(result.lifecycle, STATES.PROPOSED);
  assert.equal(coordinator.snapshot().proposalId, 'p-1');
  assert.equal(state.audit().length, 1);
});

test('canonical lifecycle accepts only the declared forward transitions', () => {
  const { coordinator } = makeCoordinator();
  coordinator.propose({ proposalId: 'p-2' });
  for (const to of [STATES.AUTHORIZED, STATES.VALIDATED, STATES.TIMED_WAIT, STATES.APPROVED, STATES.BOUND, STATES.SIMULATED, STATES.EXECUTED, STATES.VERIFIED]) {
    coordinator.advance({ actor: 'operator', to });
  }
  assert.equal(coordinator.snapshot().lifecycle, STATES.VERIFIED);
});

test('invalid lifecycle transitions fail before durable mutation', () => {
  const { coordinator, state } = makeCoordinator();
  coordinator.propose({ proposalId: 'p-3' });
  const before = state.snapshot();
  assert.throws(() => coordinator.advance({ actor: 'operator', to: STATES.APPROVED }), /INVALID_LIFECYCLE_TRANSITION/);
  assert.deepEqual(state.snapshot(), before);
});

test('authorization denial prevents lifecycle mutation', () => {
  const { coordinator, state } = makeCoordinator(() => false);
  coordinator.propose({ proposalId: 'p-4' });
  const before = state.snapshot();
  assert.throws(() => coordinator.advance({ actor: 'untrusted', to: STATES.AUTHORIZED }), /POLICY_DENIED/);
  assert.deepEqual(state.snapshot(), before);
});

test('timelock cannot be skipped and approval cannot precede it', () => {
  const { coordinator } = makeCoordinator();
  coordinator.propose({ proposalId: 'p-5' });
  coordinator.advance({ actor: 'operator', to: STATES.AUTHORIZED });
  coordinator.advance({ actor: 'operator', to: STATES.VALIDATED });
  assert.throws(() => coordinator.advance({ actor: 'operator', to: STATES.APPROVED }), /INVALID_LIFECYCLE_TRANSITION/);
  assert.equal(coordinator.snapshot().lifecycle, STATES.VALIDATED);
});

test('restart reconstructs the same lifecycle from the durable journal', () => {
  const { coordinator, journalPath } = makeCoordinator();
  coordinator.propose({ proposalId: 'p-6' });
  for (const to of [STATES.AUTHORIZED, STATES.VALIDATED, STATES.TIMED_WAIT]) {
    coordinator.advance({ actor: 'operator', to });
  }
  const recoveredState = new DurableState({}, { journalPath });
  const recovered = new LifecycleCoordinator({
    policy: new Policy(() => true),
    validator: new Validator(),
    state: recoveredState,
  });
  assert.deepEqual(recovered.snapshot(), coordinator.snapshot());
  assert.equal(recoveredState.audit().length, 4);
});

test('a second proposal cannot overwrite the durable lifecycle', () => {
  const { coordinator } = makeCoordinator();
  coordinator.propose({ proposalId: 'p-7' });
  assert.throws(() => coordinator.propose({ proposalId: 'p-8' }), /PROPOSAL_ALREADY_EXISTS/);
  assert.equal(coordinator.snapshot().proposalId, 'p-7');
});
