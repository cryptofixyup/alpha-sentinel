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

function advanceClock() {
  let now = 1000;
  return { now: () => now, advance: seconds => { now += seconds; } };
}

test('state survives restart from immutable audit records', () => {
  const filePath = db(); const { proposal, hash } = fixture();
  let clock = advanceClock();
  let lifecycle = new PersistentLifecycle({ filePath, timelockSeconds: 10, now: clock.now });
  lifecycle.create({ lifecycleId: 'p1', proposal, proposalHash: hash });
  lifecycle.transition('p1', 'HASHED');
  lifecycle.transition('p1', 'SIMULATED', { transactionHash: 'tx1' });
  lifecycle.timelock('p1', 'tx1');
  clock.advance(10);
  lifecycle.requireResimulation('p1');
  lifecycle.transition('p1', 'RESIMULATED', { transactionHash: 'tx1' });

  lifecycle = new PersistentLifecycle({ filePath, timelockSeconds: 10, now: clock.now });
  assert.equal(lifecycle.get('p1').state, 'RESIMULATED');
  assert.equal(lifecycle.get('p1').transactionHash, 'tx1');
  assert.equal(new AuditLog(filePath).verify(), true);
});

test('invalid state transitions are rejected', () => {
  const filePath = db(); const { proposal, hash } = fixture();
  const lifecycle = new PersistentLifecycle({ filePath });
  lifecycle.create({ lifecycleId: 'p1', proposal, proposalHash: hash });
  assert.throws(() => lifecycle.transition('p1', 'SIGNED'), /INVALID_STATE_TRANSITION/);
});

test('timelock cannot be bypassed', () => {
  const filePath = db(); const { proposal, hash } = fixture(); const clock = advanceClock();
  const lifecycle = new PersistentLifecycle({ filePath, timelockSeconds: 10, now: clock.now });
  lifecycle.create({ lifecycleId: 'p1', proposal, proposalHash: hash });
  lifecycle.transition('p1', 'HASHED'); lifecycle.transition('p1', 'SIMULATED', { transactionHash: 'tx1' }); lifecycle.timelock('p1', 'tx1');
  assert.throws(() => lifecycle.transition('p1', 'RESIMULATION_REQUIRED'), /TIMELOCK_ACTIVE/);
  assert.throws(() => lifecycle.transition('p1', 'APPROVED'), /INVALID_STATE_TRANSITION/);
});

test('approval requires exact re-simulation binding after timelock', () => {
  const filePath = db(); const { proposal, hash } = fixture(); const clock = advanceClock();
  const lifecycle = new PersistentLifecycle({ filePath, timelockSeconds: 1, now: clock.now });
  lifecycle.create({ lifecycleId: 'p1', proposal, proposalHash: hash }); lifecycle.transition('p1', 'HASHED'); lifecycle.transition('p1', 'SIMULATED', { transactionHash: 'tx1' }); lifecycle.timelock('p1', 'tx1');
  clock.advance(1); lifecycle.requireResimulation('p1'); lifecycle.transition('p1', 'RESIMULATED', { transactionHash: 'tx1' });
  assert.throws(() => lifecycle.transition('p1', 'APPROVED', { transactionHash: 'tx2' }), /RESIMULATION_BINDING_MISMATCH/);
  assert.equal(lifecycle.transition('p1', 'APPROVED', { transactionHash: 'tx1' }).state, 'APPROVED');
});

test('audit-chain tampering is fail-closed on restart', () => {
  const filePath = db(); const { proposal, hash } = fixture();
  const lifecycle = new PersistentLifecycle({ filePath }); lifecycle.create({ lifecycleId: 'p1', proposal, proposalHash: hash });
  const lines = fs.readFileSync(filePath, 'utf8').trim().split('\n');
  const record = JSON.parse(lines[0]); record.to = 'APPROVED'; lines[0] = JSON.stringify(record); fs.writeFileSync(filePath, `${lines.join('\n')}\n`);
  assert.throws(() => new PersistentLifecycle({ filePath }), /AUDIT_RECORD_TAMPERED/);
});
