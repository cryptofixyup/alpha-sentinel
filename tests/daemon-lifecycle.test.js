'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { Policy } = require('../core/policy');
const { Validator } = require('../core/validator');
const { DurableState } = require('../state/store');
const { AuthorizationDaemon } = require('../core/daemon');
const { STATES } = require('../core/lifecycle');

function daemon() {
  return new AuthorizationDaemon({
    policy: new Policy(actor => actor === 'operator'),
    validator: new Validator(),
    state: new DurableState(),
  });
}

test('daemon uses one canonical durable lifecycle', () => {
  const d = daemon();
  d.propose({ proposalId: 'p-1' });
  d.authorize({ actor: 'operator' });
  d.validate({ actor: 'operator' });
  d.enterTimelock({ actor: 'operator', unlockAt: 1000 });

  assert.equal(d.snapshot().lifecycle, STATES.TIMED_WAIT);
  assert.throws(() => d.approve({ actor: 'operator', now: 999 }), /TIMELOCK_ACTIVE/);

  d.approve({ actor: 'operator', now: 1000 });
  d.bind({ actor: 'operator' });
  d.simulate({ actor: 'operator' });
  d.execute({ actor: 'operator' });
  d.verify({ actor: 'operator' });
  assert.equal(d.snapshot().lifecycle, STATES.VERIFIED);
});

test('daemon cannot bypass lifecycle ordering', () => {
  const d = daemon();
  d.propose({ proposalId: 'p-2' });
  assert.throws(() => d.approve({ actor: 'operator', now: Date.now() }), /INVALID_LIFECYCLE_TRANSITION/);
  assert.throws(() => d.execute({ actor: 'operator' }), /INVALID_LIFECYCLE_TRANSITION/);
});

test('daemon authorization remains policy-controlled', () => {
  const d = daemon();
  d.propose({ proposalId: 'p-3' });
  assert.throws(() => d.authorize({ actor: 'untrusted' }), /POLICY_DENIED/);
  assert.equal(d.snapshot().lifecycle, STATES.PROPOSED);
});

test('timelock cannot be skipped or approved before unlock', () => {
  const d = daemon();
  d.propose({ proposalId: 'p-4' });
  d.authorize({ actor: 'operator' });
  d.validate({ actor: 'operator' });
  assert.throws(() => d.approve({ actor: 'operator', now: 1000 }), /INVALID_LIFECYCLE_TRANSITION/);
  d.enterTimelock({ actor: 'operator', unlockAt: 2000 });
  assert.throws(() => d.approve({ actor: 'operator', now: 1999 }), /TIMELOCK_ACTIVE/);
});
