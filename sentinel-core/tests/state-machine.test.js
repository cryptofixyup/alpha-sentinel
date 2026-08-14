import test from 'node:test';
import assert from 'node:assert/strict';
import { createProposal } from '../proposals/proposal.js';
import { DurableState } from '../state/store.js';
import { STATES } from '../lifecycle/state.js';

function makeStore() {
  return new DurableState({ state: STATES.PROPOSED, proposalId: null }, ['policy-engine']);
}

function proposal(id, version, actor = 'policy-engine') {
  return createProposal({ id, actor, expectedVersion: version, payload: { action: 'test' } });
}

test('accepts only permitted deterministic transitions', () => {
  const store = makeStore();
  const result = store.transition(proposal('p1', 0), STATES.VALIDATED);
  assert.equal(result.state.state, STATES.VALIDATED);
  assert.equal(result.version, 1);
});

test('rejects illegal transitions', () => {
  const store = makeStore();
  assert.throws(() => store.transition(proposal('p1', 0), STATES.COMPLETED), /INVALID_TRANSITION/);
});

test('rejects stale proposals', () => {
  const store = makeStore();
  store.transition(proposal('p1', 0), STATES.VALIDATED);
  assert.throws(() => store.transition(proposal('p2', 0), STATES.APPROVED), /STALE_PROPOSAL/);
});

test('rejects duplicate proposals', () => {
  const store = makeStore();
  store.transition(proposal('p1', 0), STATES.VALIDATED);
  assert.throws(() => store.transition(proposal('p1', 1), STATES.APPROVED), /DUPLICATE_PROPOSAL/);
});

test('rejects unauthorized actors before state mutation', () => {
  const store = makeStore();
  assert.throws(() => store.transition(proposal('evil', 0, 'untrusted-agent'), STATES.VALIDATED), /UNAUTHORIZED_ACTOR/);
  assert.equal(store.read().version, 0);
  assert.equal(store.read().state.state, STATES.PROPOSED);
});

test('proposals are deeply immutable', () => {
  const p = proposal('immutable', 0);
  assert(Object.isFrozen(p));
  assert(Object.isFrozen(p.payload));
  assert.throws(() => { p.payload.action = 'mutate'; }, TypeError);
});
