import test from 'node:test';
import assert from 'node:assert/strict';
import { createProposal } from '../proposals/proposal.js';
import { createPolicy } from '../policy/policy.js';
import { validate } from '../lifecycle/machine.js';
import { DurableState } from '../state/store.js';
import { STATES } from '../lifecycle/state.js';

const policy = createPolicy({ actors: ['policy-engine'], operations: ['TEST'], now: 0 });

function makeStore() {
  return new DurableState({ state: STATES.PROPOSED, proposalId: null });
}

function proposal(id, version, actor = 'policy-engine') {
  return createProposal({
    id,
    actor,
    expectedVersion: version,
    payload: { operation: 'TEST', expiresAt: 100 },
  });
}

test('commits only a validated transition', () => {
  const store = makeStore();
  const current = store.read();
  const validated = validate({
    current: { ...current, state: current.state.state },
    proposal: proposal('p1', 0),
    to: STATES.VALIDATED,
    policy,
  });
  const result = store.commit(validated);
  assert.equal(result.state.state, STATES.VALIDATED);
  assert.equal(result.version, 1);
});

test('rejects raw proposal mutation through the state store', () => {
  const store = makeStore();
  assert.throws(() => store.commit(proposal('p1', 0)), /UNVALIDATED_TRANSITION/);
  assert.equal(store.read().version, 0);
});

test('rejects a stale validated transition', () => {
  const store = makeStore();
  const current = store.read();
  const validated = validate({ current: { ...current, state: current.state.state }, proposal: proposal('p1', 0), to: STATES.VALIDATED, policy });
  store.commit(validated);
  assert.throws(() => store.commit(validated), /STALE_VALIDATED_TRANSITION|DUPLICATE_PROPOSAL/);
});

test('rejects unauthorized proposals before validation', () => {
  const store = makeStore();
  const current = store.read();
  assert.throws(
    () => validate({ current: { ...current, state: current.state.state }, proposal: proposal('evil', 0, 'untrusted-agent'), to: STATES.VALIDATED, policy }),
    /POLICY_DENIED/
  );
  assert.equal(store.read().version, 0);
});

test('rejects illegal lifecycle transitions before commit', () => {
  const store = makeStore();
  const current = store.read();
  assert.throws(
    () => validate({ current: { ...current, state: current.state.state }, proposal: proposal('p1', 0), to: STATES.COMPLETED, policy }),
    /INVALID_TRANSITION/
  );
  assert.equal(store.read().version, 0);
});
