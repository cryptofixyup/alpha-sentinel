'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { Policy } = require('../core/policy');
const { Validator } = require('../core/validator');
const { DurableState } = require('../state/store');
const { AuthorizationDaemon } = require('../core/daemon');
const { RouterAdapter } = require('../core/router-adapter');
const { SimulationBoundary } = require('../simulation/boundary');

function daemon() {
  const policy = new Policy(actor => actor === 'operator');
  const validator = new Validator();
  const state = new DurableState();
  const routerAdapter = new RouterAdapter({
    policy,
    validator,
    state,
    build: ({ proposalId, proposalHash, payload }) => ({ proposalId, proposalHash, payload }),
  });
  const simulationBoundary = new SimulationBoundary(() => ({ ok: true }));
  return new AuthorizationDaemon({ policy, validator, state, routerAdapter, simulationBoundary });
}

test('approval before timelock configuration reports lifecycle violation', () => {
  const d = daemon();
  d.propose({ proposalId: 'p-order', proposalHash: 'hash-p-order', payload: {} });
  d.authorize({ actor: 'operator' });
  d.validate({ actor: 'operator' });
  assert.throws(
    () => d.approve({ actor: 'operator', now: 1000 }),
    /INVALID_LIFECYCLE_TRANSITION:VALIDATED->APPROVED/
  );
});

test('approval during configured timelock remains blocked by timelock', () => {
  const d = daemon();
  d.propose({ proposalId: 'p-active', proposalHash: 'hash-p-active', payload: {} });
  d.authorize({ actor: 'operator' });
  d.validate({ actor: 'operator' });
  d.enterTimelock({ actor: 'operator', unlockAt: 2000 });
  assert.throws(() => d.approve({ actor: 'operator', now: 1999 }), /TIMELOCK_ACTIVE/);
});
