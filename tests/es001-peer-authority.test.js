'use strict';

// Synthetic peer framing: this repository has no production peer ingress.
// Uses real modules and the operator rule from tests/daemon-lifecycle.test.js.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');
const { Policy } = require('../core/policy');
const { Validator } = require('../core/validator');
const { DurableState } = require('../state/store');
const { RouterAdapter } = require('../core/router-adapter');
const { SimulationBoundary } = require('../simulation/boundary');
const { AuthorizationDaemon } = require('../core/daemon');
const { LifecycleCoordinator, STATES } = require('../core/lifecycle');

// Test-only ingress contract. Trusted actor is supplied separately from peer bytes.
// This adapter is not present in the pinned production tree.
function dispatchPeerGo(daemon, trustedActor, peerMessage) {
  assert.equal(peerMessage.type, 'GO');
  return daemon.authorize({ actor: trustedActor });
}

const digest = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
function fixture(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'es001-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const journalPath = path.join(dir, 'state.jsonl');
  const state = new DurableState({}, { journalPath });
  const policy = new Policy(actor => actor === 'operator');
  const validator = new Validator();
  const routerAdapter = new RouterAdapter({ policy, validator, state,
    build: ({ proposalId, proposalHash, payload }) => ({ proposalId, proposalHash, payload }) });
  const simulationBoundary = new SimulationBoundary(tx => ({ ok: true, proposalId: tx.proposalId }));
  const dependencies = { policy, validator, state, routerAdapter, simulationBoundary };
  const daemon = new AuthorizationDaemon(dependencies);
  daemon.propose({ proposalId: 'es001-p1', proposalHash: digest('proposal'), payload: { action: 'test-only' } });
  return { dir, journalPath, state, policy, validator, daemon, dependencies };
}

function rejected(t, id, actor, peerMessage) {
  const f = fixture(t);
  const before = f.state.snapshot();
  const journalBefore = fs.readFileSync(f.journalPath);
  let observedError;
  assert.throws(() => dispatchPeerGo(f.daemon, actor, peerMessage), error => {
    observedError = error.message;
    return error.message === 'POLICY_DENIED';
  });
  const after = f.state.snapshot();
  assert.deepEqual(after, before);
  const journalAfter = fs.readFileSync(f.journalPath);
  assert.deepEqual(journalAfter, journalBefore);
  assert.deepEqual(new DurableState({}, { journalPath: f.journalPath }).snapshot(), before);
  const evidenceDir = process.env.ES001_EVIDENCE_DIR || path.join(f.dir, 'evidence');
  fs.mkdirSync(evidenceDir, { recursive: true });
  const evidencePath = path.join(evidenceDir, `${id}.json`);
  const entry = {
    schema: 'es001-local-rejection-v1', id, scope: 'synthetic-framing-real-policy-boundary',
    sourceBaseSha: '05a7f316bf9e56e5b76a4acdc7225396757f35bf',
    commitSha: execFileSync('git', ['rev-parse', 'HEAD'], {
      cwd: path.join(__dirname, '..'), encoding: 'utf8',
    }).trim(),
    nodeVersion: process.version, timestamp: new Date().toISOString(),
    actor: actor ?? null, peerMessage, observedError, before, after,
    journalBeforeSha256: digest(journalBefore), journalAfterSha256: digest(journalAfter),
    recoveredSnapshot: new DurableState({}, { journalPath: f.journalPath }).snapshot(),
  };
  // Evidence is outside the lifecycle journal. An I/O error fails the test.
  const fd = fs.openSync(evidencePath, 'wx');
  try { fs.writeFileSync(fd, JSON.stringify(entry, null, 2) + '\n'); fs.fsyncSync(fd); }
  finally { fs.closeSync(fd); }
  assert.deepEqual(JSON.parse(fs.readFileSync(evidencePath, 'utf8')), entry);
}

test('ES001 peer denied without state or journal mutation', t => {
  rejected(t, 'peer-denied', 'peer', { type: 'GO', payload: { requestedState: 'AUTHORIZED' } });
});

test('ES001 peer claimed operator payload cannot grant authority at boundary', t => {
  // The transport actor is supplied separately. This is NOT a production ingress test.
  const peerMessage = { type: 'GO', actor: 'operator', payload: { actor: 'operator', requestedState: 'AUTHORIZED' } };
  rejected(t, 'peer-spoof-denied', 'peer', peerMessage);
});

test('ES001 missing actor denied', t => {
  rejected(t, 'missing-actor-denied', undefined, { type: 'GO', payload: { actor: 'operator' } });
});

test('ES001 GO used as actor cannot authorize', t => {
  rejected(t, 'go-actor-denied', 'GO', { type: 'GO', payload: 'peer fabricated' });
});

test('ES001 direct lifecycle peer advance denied without mutation', t => {
  const { dependencies, state } = fixture(t);
  const coordinator = new LifecycleCoordinator(dependencies);
  const before = state.snapshot();
  assert.throws(() => coordinator.advance({ actor: 'peer', to: STATES.AUTHORIZED }),
    { message: 'POLICY_DENIED' });
  assert.deepEqual(state.snapshot(), before);
});

test('ES001 operator positive control reaches simulated through real boundaries', t => {
  const { daemon, state } = fixture(t);
  const before = state.snapshot();
  assert.throws(() => daemon.authorize({ actor: 'peer' }), { message: 'POLICY_DENIED' });
  assert.deepEqual(state.snapshot(), before);
  const result = daemon.authorize({ actor: 'operator' });
  assert.equal(result.actor, 'operator');
  assert.equal(result.lifecycle, 'AUTHORIZED');
  assert.equal(state.snapshot().data.lifecycle.proposalId, 'es001-p1');
  daemon.validate({ actor: 'operator' });
  assert.equal(daemon.bind({ actor: 'operator' }).kind, 'BoundTransaction');
  assert.equal(daemon.simulate({ actor: 'operator' }).ok, true);
  assert.equal(daemon.snapshot().lifecycle, 'SIMULATED');
});

test('ES001 Validator rejects stale expectedVersion using real set shape', t => {
  const { state, validator } = fixture(t);
  const before = state.snapshot();
  assert.throws(() => validator.validate({ state: before,
    transition: { type: 'set', expectedVersion: before.version - 1, payload: { key: 'probe', value: 1 } } }),
  { message: 'VERSION_CONFLICT' });
  assert.deepEqual(state.snapshot(), before);
});

test('ES001 DurableState rejects replay of a real ValidatedTransition', t => {
  const { state, validator } = fixture(t);
  const snap = state.snapshot();
  const validated = validator.validate({ state: snap,
    transition: { type: 'set', expectedVersion: snap.version, payload: { key: 'probe', value: 1 } } });
  assert.equal(validated.kind, 'ValidatedTransition');
  state.apply(validated);
  const before = state.snapshot();
  assert.throws(() => state.apply(validated), { message: 'VERSION_CONFLICT' });
  assert.deepEqual(state.snapshot(), before);
  // Optimistic version conflict only; no approval-artifact replay claim.
});

test('ES001 DurableState rejects unvalidated set transition', t => {
  const { state } = fixture(t);
  const before = state.snapshot();
  assert.throws(() => state.apply({ type: 'set', expectedVersion: before.version,
    payload: { key: 'probe', value: 1 } }), { message: 'VALIDATED_TRANSITION_REQUIRED' });
  assert.deepEqual(state.snapshot(), before);
});

test('ES001 missing interfaces throw instead of skip', t => {
  const { dependencies } = fixture(t);
  assert.throws(() => new AuthorizationDaemon({ ...dependencies, routerAdapter: undefined }),
    { message: 'routerAdapter required' });
  assert.throws(() => new AuthorizationDaemon({ ...dependencies, simulationBoundary: undefined }),
    { message: 'simulationBoundary required' });
});
