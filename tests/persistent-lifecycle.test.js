'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { PersistentLifecycle, canonical } = require('../state/persistent-lifecycle');
const { AuditLog } = require('../state/audit-log');

function fixture() {
  const proposal = { actor: 'policy', transition: { type: 'set', payload: { key: 'x', value: 1 } } };
  return { proposal, hash: crypto.createHash('sha256').update(canonical(proposal)).digest('hex') };
}
function db() { return path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'alpha-sentinel-')), 'audit.jsonl'); }
function advanceClock(start = 1000) { let now = start; return { now: () => now, advance: seconds => { now += seconds; } }; }
function lifecycleWithSimulation(clock = advanceClock(), timelockSeconds = 10) {
  const filePath = db(); const { proposal, hash } = fixture();
  const lifecycle = new PersistentLifecycle({ filePath, timelockSeconds, now: clock.now });
  lifecycle.create({ lifecycleId: 'p1', proposal, proposalHash: hash });
  lifecycle.transition('p1', 'HASHED');
  lifecycle.transition('p1', 'SIMULATED', { transactionHash: 'tx1' });
  return { filePath, lifecycle, clock, proposal, hash };
}

test('state survives restart from immutable audit records', () => {
  const { filePath, lifecycle, clock } = lifecycleWithSimulation();
  lifecycle.timelock('p1', 'tx1'); clock.advance(10); lifecycle.requireResimulation('p1'); lifecycle.transition('p1', 'RESIMULATED', { transactionHash: 'tx1' });
  const restarted = new PersistentLifecycle({ filePath, timelockSeconds: 10, now: clock.now });
  assert.equal(restarted.get('p1').state, 'RESIMULATED');
  assert.equal(restarted.get('p1').transactionHash, 'tx1');
  assert.equal(new AuditLog(filePath).verify(), true);
});

test('invalid state transitions are rejected', () => {
  const { lifecycle } = lifecycleWithSimulation();
  assert.throws(() => lifecycle.transition('p1', 'SIGNED'), /INVALID_STATE_TRANSITION/);
});

test('proposal hash substitution is rejected', () => {
  const filePath = db(); const { proposal } = fixture(); const lifecycle = new PersistentLifecycle({ filePath });
  const fakeHash = crypto.createHash('sha256').update(canonical({ ...proposal, transition: { type: 'set', payload: { key: 'x', value: 2 } } })).digest('hex');
  assert.throws(() => lifecycle.create({ lifecycleId: 'p1', proposal, proposalHash: fakeHash }), /PROPOSAL_HASH_MISMATCH/);
});

test('duplicate lifecycle creation is rejected', () => {
  const { filePath, proposal, hash } = fixture(); const lifecycle = new PersistentLifecycle({ filePath });
  lifecycle.create({ lifecycleId: 'p1', proposal, proposalHash: hash });
  assert.throws(() => lifecycle.create({ lifecycleId: 'p1', proposal, proposalHash: hash }), /LIFECYCLE_EXISTS/);
});

test('timelock cannot be bypassed through transition', () => {
  const { lifecycle, clock } = lifecycleWithSimulation();
  lifecycle.timelock('p1', 'tx1');
  assert.throws(() => lifecycle.transition('p1', 'RESIMULATION_REQUIRED'), /TIMELOCK_ACTIVE/);
  clock.advance(10);
  assert.equal(lifecycle.transition('p1', 'RESIMULATION_REQUIRED').state, 'RESIMULATION_REQUIRED');
});

test('timelock cannot be reset or rebound', () => {
  const { lifecycle } = lifecycleWithSimulation();
  lifecycle.timelock('p1', 'tx1');
  assert.throws(() => lifecycle.timelock('p1', 'tx2'), /SIMULATION_REQUIRED/);
});

test('timelock rejects an unbound transaction hash', () => {
  const { lifecycle } = lifecycleWithSimulation();
  assert.throws(() => lifecycle.timelock('p1', 'tx2'), /TRANSACTION_BINDING_MISMATCH/);
});

test('approval cannot bypass timelock and re-simulation', () => {
  const { lifecycle } = lifecycleWithSimulation();
  assert.throws(() => lifecycle.transition('p1', 'APPROVED', { transactionHash: 'tx1' }), /INVALID_STATE_TRANSITION/);
});

test('re-simulation of a different transaction is rejected', () => {
  const { lifecycle, clock } = lifecycleWithSimulation();
  lifecycle.timelock('p1', 'tx1'); clock.advance(10); lifecycle.requireResimulation('p1');
  assert.throws(() => lifecycle.transition('p1', 'RESIMULATED', { transactionHash: 'tx2' }), /RESIMULATION_BINDING_MISMATCH/);
});

test('approval requires exact re-simulation binding', () => {
  const { lifecycle, clock } = lifecycleWithSimulation();
  lifecycle.timelock('p1', 'tx1'); clock.advance(10); lifecycle.requireResimulation('p1'); lifecycle.transition('p1', 'RESIMULATED', { transactionHash: 'tx1' });
  assert.throws(() => lifecycle.transition('p1', 'APPROVED', { transactionHash: 'tx2' }), /APPROVAL_BINDING_MISMATCH/);
  assert.equal(lifecycle.transition('p1', 'APPROVED', { transactionHash: 'tx1' }).state, 'APPROVED');
});

test('terminal lifecycle states cannot transition', () => {
  const filePath = db(); const { proposal, hash } = fixture(); const lifecycle = new PersistentLifecycle({ filePath });
  lifecycle.create({ lifecycleId: 'p1', proposal, proposalHash: hash }); lifecycle.transition('p1', 'REJECTED');
  assert.throws(() => lifecycle.transition('p1', 'HASHED'), /LIFECYCLE_TERMINAL/);
});

test('audit-chain tampering is fail-closed on restart', () => {
  const filePath = db(); const { proposal, hash } = fixture(); const lifecycle = new PersistentLifecycle({ filePath });
  lifecycle.create({ lifecycleId: 'p1', proposal, proposalHash: hash });
  const lines = fs.readFileSync(filePath, 'utf8').trim().split('\n');
  const record = JSON.parse(lines[0]); record.to = 'APPROVED'; lines[0] = JSON.stringify(record); fs.writeFileSync(filePath, `${lines.join('\n')}\n`);
  assert.throws(() => new PersistentLifecycle({ filePath }), /AUDIT_RECORD_TAMPERED/);
});

test('audit truncation is fail-closed on restart', () => {
  const { filePath, lifecycle } = lifecycleWithSimulation();
  lifecycle.timelock('p1', 'tx1');
  const lines = fs.readFileSync(filePath, 'utf8').trim().split('\n');
  fs.writeFileSync(filePath, `${lines.slice(0, -1).join('\n')}\n`);
  assert.throws(() => new PersistentLifecycle({ filePath }), /AUDIT_TERMINAL_CHECKPOINT_MISMATCH/);
});

test('missing lifecycle is rejected', () => {
  const lifecycle = new PersistentLifecycle({ filePath: db() });
  assert.throws(() => lifecycle.get('missing'), /LIFECYCLE_NOT_FOUND/);
});
