import test from 'node:test';
import assert from 'node:assert/strict';
import { createProposal } from '../proposals/proposal.js';
import { createPolicy, DECISIONS, authorize } from '../policy/policy.js';
import { validateTransition } from '../lifecycle/validator.js';
import { STATES } from '../lifecycle/state.js';

const policy = createPolicy({ actors: ['operator-1'], operations: ['TRANSFER'], now: 100 });
const state = { state: STATES.PROPOSED, version: 0, proposalId: null };

function proposal(overrides = {}) {
  return createProposal({
    id: 'p-1',
    actor: 'operator-1',
    expectedVersion: 0,
    payload: { operation: 'TRANSFER', expiresAt: 200 },
    ...overrides,
  });
}

test('allows an authorized proposal', () => {
  assert.equal(authorize({ proposal: proposal(), state, policy }), DECISIONS.ALLOW);
});

test('denies a missing or invalid policy', () => {
  assert.equal(authorize({ proposal: proposal(), state, policy: null }), DECISIONS.DENY);
});

test('denies an expired proposal', () => {
  const p = proposal({ payload: { operation: 'TRANSFER', expiresAt: 100 } });
  assert.equal(authorize({ proposal: p, state, policy }), DECISIONS.DENY);
});

test('denies the wrong actor', () => {
  const p = proposal({ actor: 'intruder' });
  assert.equal(authorize({ proposal: p, state, policy }), DECISIONS.DENY);
});

test('denies the wrong operation', () => {
  const p = proposal({ payload: { operation: 'DELETE', expiresAt: 200 } });
  assert.equal(authorize({ proposal: p, state, policy }), DECISIONS.DENY);
});

test('denies a stale proposal', () => {
  const p = proposal({ expectedVersion: 1 });
  assert.equal(authorize({ proposal: p, state, policy }), DECISIONS.DENY);
});

test('rejects replay of an already consumed proposal', () => {
  const p = proposal();
  assert.throws(
    () => validateTransition({ current: { ...state, proposalId: 'p-1' }, proposal: p, target: STATES.VALIDATED, policy }),
    /DUPLICATE_PROPOSAL/
  );
});

test('rejects an illegal lifecycle transition', () => {
  const p = proposal();
  assert.throws(
    () => validateTransition({ current: state, proposal: p, target: STATES.COMPLETED, policy }),
    /INVALID_TRANSITION/
  );
});
