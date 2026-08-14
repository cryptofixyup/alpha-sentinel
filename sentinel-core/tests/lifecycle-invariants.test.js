import test from 'node:test';
import assert from 'node:assert/strict';
import { STATES, canTransition, transition } from '../lifecycle/state.js';
import { createProposal } from '../proposals/proposal.js';
import { createPolicy, authorize, DECISIONS } from '../policy/policy.js';
import { validate } from '../lifecycle/validator.js';
import { DurableState } from '../state/store.js';

test('transition matrix accepts only explicitly permitted edges', () => {
  const states = Object.values(STATES);
  for (const from of states) {
    for (const to of states) {
      const allowed = canTransition(from, to);
      if (allowed) assert.doesNotThrow(() => transition(from, to));
      else assert.throws(() => transition(from, to), /INVALID_TRANSITION/);
    }
  }
});

test('terminal states cannot transition', () => {
  for (const state of [STATES.COMPLETED, STATES.REJECTED, STATES.FAILED]) {
    assert.deepEqual(
      Object.values(STATES).filter(target => canTransition(state, target)),
      []
    );
  }
});

test('rejected validation never mutates durable state', () => {
  const store = new DurableState({ state: STATES.PROPOSED, proposalId: null });
  const before = store.read();
  const proposal = createProposal({
    id: 'illegal-1', actor: 'agent-a', expectedVersion: 0,
    payload: { operation: 'EXECUTE', expiresAt: 100 },
  });
  const policy = createPolicy({ actors: ['agent-a'], operations: ['EXECUTE'], now: 0 });
  const decision = authorize({ proposal, state: before, policy });
  assert.equal(decision, DECISIONS.ALLOW);
  assert.throws(() => validate({ proposal, state: before, policyDecision: decision, target: STATES.COMPLETED }), /INVALID_TRANSITION/);
  assert.deepEqual(store.read(), before);
});

test('successful commit changes state and version exactly once', () => {
  const store = new DurableState({ state: STATES.PROPOSED, proposalId: null });
  const before = store.read();
  const proposal = createProposal({
    id: 'valid-1', actor: 'agent-a', expectedVersion: before.version,
    payload: { operation: 'VALIDATE', expiresAt: 100 },
  });
  const policy = createPolicy({ actors: ['agent-a'], operations: ['VALIDATE'], now: 0 });
  const decision = authorize({ proposal, state: before, policy });
  const validated = validate({ proposal, state: before, policyDecision: decision, target: STATES.VALIDATED });
  const after = store.commit(validated);
  assert.equal(after.state, STATES.VALIDATED);
  assert.equal(after.version, before.version + 1);
  assert.equal(after.proposalId, proposal.id);
});

test('replay and stale commits cannot mutate state', () => {
  const store = new DurableState({ state: STATES.PROPOSED, proposalId: null });
  const proposal = createProposal({ id: 'once', actor: 'agent-a', expectedVersion: 0, payload: { operation: 'VALIDATE' } });
  const policy = createPolicy({ actors: ['agent-a'], operations: ['VALIDATE'] });
  const first = store.read();
  const validated = validate({ proposal, state: first, policyDecision: authorize({ proposal, state: first, policy }), target: STATES.VALIDATED });
  store.commit(validated);
  const after = store.read();
  assert.throws(() => store.commit(validated), /STALE_VALIDATED_TRANSITION|DUPLICATE_PROPOSAL/);
  assert.deepEqual(store.read(), after);
});
