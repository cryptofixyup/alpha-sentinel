'use strict';

// Tests only: real router and journal boundaries at the pinned source revision.
// Removing an input/recovery guard must fail its corresponding exact-error test.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { BoundTransaction, RouterAdapter } = require('../core/router-adapter');
const { Policy } = require('../core/policy');
const { Validator } = require('../core/validator');
const { DurableState, hashCanonical } = require('../state/store');
const { AuthorizationDaemon } = require('../core/daemon');
const { SimulationBoundary } = require('../simulation/boundary');
const { STATES } = require('../core/lifecycle');

const envelope = { proposalId: 'router-journal', proposalHash: 'hash-router-journal', payload: {} };

function routerFixture(build = ({ payload }) => payload) {
  const policy = new Policy(actor => actor === 'operator');
  const validator = new Validator();
  const state = new DurableState();
  const routerAdapter = new RouterAdapter({ policy, validator, state, build });
  const daemon = new AuthorizationDaemon({ policy, validator, state, routerAdapter,
    simulationBoundary: new SimulationBoundary(() => ({ ok: true })) });
  daemon.propose(envelope);
  daemon.authorize({ actor: 'operator' });
  daemon.validate({ actor: 'operator' });
  return { routerAdapter, daemon, state };
}

function journalFixture(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'router-journal-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const journalPath = path.join(dir, 'state.jsonl');
  const state = new DurableState({}, { journalPath });
  state.apply(new Validator().validate({ state: state.snapshot(), transition: {
    type: 'set', payload: { key: 'probe', value: 1 }, expectedVersion: 0,
  } }));
  assert.deepEqual(new DurableState({}, { journalPath }).snapshot(), state.snapshot());
  return { journalPath, record: JSON.parse(fs.readFileSync(journalPath, 'utf8')) };
}

function rejectRecovery(journalPath, bytes, message) {
  fs.writeFileSync(journalPath, bytes);
  assert.throws(() => new DurableState({}, { journalPath }), { message });
  assert.equal(fs.readFileSync(journalPath, 'utf8'), bytes);
}

function encodeRecord(record) {
  const { recordHash, ...body } = record;
  // Keep the checksum valid to isolate semantic transition validation.
  return JSON.stringify({ ...body, recordHash: hashCanonical(body) }) + '\n';
}

test('01 BoundTransaction rejects missing or invalid proposalId', () => {
  for (const proposalId of [undefined, null, '', 1]) {
    assert.throws(() => new BoundTransaction({ ...envelope, proposalId }),
      { message: 'PROPOSAL_ID_REQUIRED' });
  }
});

test('02 BoundTransaction rejects missing or invalid proposalHash', () => {
  for (const proposalHash of [undefined, null, '', 1]) {
    assert.throws(() => new BoundTransaction({ ...envelope, proposalHash }),
      { message: 'PROPOSAL_HASH_REQUIRED' });
  }
});

test('03 BoundTransaction rejects null, array, and non-object payloads', () => {
  for (const payload of [undefined, null, [], 'text', 1, false]) {
    assert.throws(() => new BoundTransaction({ ...envelope, payload }),
      { message: 'MALFORMED_TRANSACTION_ENVELOPE' });
  }
});

test('04 construct rejects missing or non-string proposal identity', () => {
  const { routerAdapter, state } = routerFixture();
  const before = state.snapshot();
  for (const field of ['proposalId', 'proposalHash']) {
    for (const value of [undefined, null, '', 1]) {
      assert.throws(() => routerAdapter.construct({ ...envelope, actor: 'operator', [field]: value }),
        { message: 'PROPOSAL_ID_AND_HASH_REQUIRED' });
      assert.deepEqual(state.snapshot(), before);
    }
  }
});

test('05 construct rejects null, array, and non-object payloads', () => {
  const { routerAdapter, state } = routerFixture();
  const before = state.snapshot();
  for (const payload of [undefined, null, [], 'text', 1, false]) {
    assert.throws(() => routerAdapter.construct({ ...envelope, actor: 'operator', payload }),
      { message: 'MALFORMED_TRANSACTION_ENVELOPE' });
    assert.deepEqual(state.snapshot(), before);
  }
});

test('06 null or array build output cannot bind or mutate VALIDATED lifecycle', () => {
  for (const output of [null, []]) {
    const { daemon, state } = routerFixture(() => output);
    const before = state.snapshot();
    assert.equal(daemon.snapshot().lifecycle, STATES.VALIDATED);
    assert.throws(() => daemon.bind({ actor: 'operator' }),
      { message: 'MALFORMED_TRANSACTION_ENVELOPE' });
    assert.equal(daemon.snapshot().lifecycle, STATES.VALIDATED);
    assert.deepEqual(state.snapshot(), before);
  }
});

test('07 corrupt journal JSON fails recovery', t => {
  const { journalPath } = journalFixture(t);
  rejectRecovery(journalPath, '{broken-json}\n', 'CORRUPT_JOURNAL_RECORD');
});

test('08 missing final newline fails recovery', t => {
  const { journalPath, record } = journalFixture(t);
  rejectRecovery(journalPath, JSON.stringify(record), 'CORRUPT_JOURNAL_TRAILING_DATA');
});

test('09 invalid transition kind fails recovery despite valid record hash', t => {
  const { journalPath, record } = journalFixture(t);
  record.transition.kind = 'UnvalidatedTransition';
  rejectRecovery(journalPath, encodeRecord(record), 'AUDIT_TRANSITION_INVALID');
});

test('10 transition expectedVersion mismatch fails recovery despite valid record hash', t => {
  const { journalPath, record } = journalFixture(t);
  record.transition.expectedVersion = record.versionBefore + 1;
  rejectRecovery(journalPath, encodeRecord(record), 'AUDIT_TRANSITION_VERSION_INVALID');
});
