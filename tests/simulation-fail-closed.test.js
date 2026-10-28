'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { Policy } = require('../core/policy');
const { Validator } = require('../core/validator');
const { DurableState } = require('../state/store');
const { AuthorizationDaemon } = require('../core/daemon');
const { RouterAdapter } = require('../core/router-adapter');
const { SimulationBoundary } = require('../simulation/boundary');
const { STATES } = require('../core/lifecycle');

test('constructor requires an explicit simulator function', () => {
  for (const value of [undefined, null, false, 0, '', {}]) {
    assert.throws(() => new SimulationBoundary(value), {
      name: 'TypeError',
      message: 'simulator function required',
    });
  }
});

test('simulation fails closed for false, null, primitive, and throwing results', () => {
  const bound = { kind: 'BoundTransaction', proposalId: 'p-1' };
  const badSimulators = [
    () => ({ ok: false }),
    () => null,
    () => 'ok',
    () => 1,
    () => { throw new Error('provider detail'); },
  ];
  for (const simulator of badSimulators) {
    assert.throws(() => new SimulationBoundary(simulator).simulate(bound), {
      message: 'SIMULATION_FAILED',
    });
  }
});

test('simulation fails closed when result cannot be cloned', () => {
  const bound = { kind: 'BoundTransaction', proposalId: 'p-clone' };
  const result = { ok: true, unsupported: () => 'not cloneable' };
  assert.throws(() => new SimulationBoundary(() => result).simulate(bound), {
    message: 'SIMULATION_FAILED',
  });
});

function makeDaemon(simulator) {
  const policy = new Policy(actor => actor === 'operator');
  const validator = new Validator();
  const state = new DurableState();
  const routerAdapter = new RouterAdapter({
    policy,
    validator,
    state,
    build: ({ proposalId, proposalHash, payload }) => ({ proposalId, proposalHash, payload }),
  });
  const simulationBoundary = new SimulationBoundary(simulator);
  return new AuthorizationDaemon({ policy, validator, state, routerAdapter, simulationBoundary });
}

function bindProposal(daemon, proposalId) {
  daemon.propose({ proposalId, proposalHash: `hash-${proposalId}`, payload: { action: 'test' } });
  daemon.authorize({ actor: 'operator' });
  daemon.validate({ actor: 'operator' });
  daemon.bind({ actor: 'operator' });
}

test('failed initial simulation leaves lifecycle at BOUND', () => {
  const daemon = makeDaemon(() => ({ ok: false }));
  bindProposal(daemon, 'initial-fail');
  assert.throws(() => daemon.simulate({ actor: 'operator' }), { message: 'SIMULATION_FAILED' });
  assert.equal(daemon.snapshot().lifecycle, STATES.BOUND);
});

test('failed post-timelock re-simulation leaves lifecycle at TIMED_WAIT', () => {
  let calls = 0;
  const daemon = makeDaemon(() => {
    calls += 1;
    return calls === 1 ? { ok: true, phase: 'initial' } : { ok: false, phase: 'resimulation' };
  });
  bindProposal(daemon, 'resim-fail');
  daemon.simulate({ actor: 'operator' });
  daemon.enterTimelock({ actor: 'operator', unlockAt: 1000 });

  assert.throws(() => daemon.resimulate({ actor: 'operator', now: 1000 }), {
    message: 'SIMULATION_FAILED',
  });
  assert.equal(daemon.snapshot().lifecycle, STATES.TIMED_WAIT);
});

test('explicit successful simulator supports initial and post-timelock simulation', () => {
  const daemon = makeDaemon(bound => ({ ok: true, proposalId: bound.proposalId }));
  bindProposal(daemon, 'happy-path');

  assert.equal(daemon.simulate({ actor: 'operator' }).ok, true);
  assert.equal(daemon.snapshot().lifecycle, STATES.SIMULATED);

  daemon.enterTimelock({ actor: 'operator', unlockAt: 1000 });
  daemon.resimulate({ actor: 'operator', now: 1000 });
  assert.equal(daemon.snapshot().lifecycle, STATES.RE_SIMULATED);
  assert.equal(daemon.snapshot().metadata.resimulation.ok, true);
});
