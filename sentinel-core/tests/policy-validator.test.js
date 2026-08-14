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

test('allows a later lifecycle transition for the same proposal identity', () => {
  const current = { state: STATES.VALIDATED, version: 1, proposalId: 'p-1' };
  const p = proposal({ expectedVersion: 1 });
  const validated = validateTransition({ current, proposal: p, target: STATES.APPROVED, policy });
  assert.equal(validated.proposalId, 'p-1');
  assert.equal(validated.fromVersion, 1);
  assert.equal(validated.target, STATES.APPROVED);
});

test('rejects an illegal lifecycle transition', () => {
  const p = proposal();
  assert.throws(
    () => validateTransition({ current: state, proposal: p, target: STATES.COMPLETED, policy }),
    /INVALID_TRANSITION/
  );
});
