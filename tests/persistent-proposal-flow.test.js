'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { PersistentLifecycle } = require('../state/persistent-lifecycle');
const { ProposalFlow } = require('../daemon/proposal-flow');

function tempStore() {
  return path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'alpha-sentinel-')), 'lifecycle.log');
}

function policy(input) {
  return { approved: input.sizePct > 0 && input.sizePct <= 0.15 && input.riskScore <= 1 };
}

function createFlow(file, nowRef) {
  const store = new PersistentLifecycle(file, { clock: () => nowRef.value });
  const flow = new ProposalFlow({ lifecycle: store, policy });
  const proposal = flow.propose({ asset: 'ETH', direction: 'LONG', sizePct: 0.01, calculatedEdge: 0.1, riskScore: 0.1 });
  return { store, proposal };
}

test('daemon proposal flow persists through restart', () => {
  const file = tempStore();
  const nowRef = { value: 1000 };
  const { store: first, proposal } = createFlow(file, nowRef);
  assert.equal(first.get(proposal.proposalId).state, 'CREATED');
  first.transition(proposal.proposalId, 'HASHED');
  first.bindTransaction(proposal.proposalId, 'tx-binding-1');
  first.recordSimulation(proposal.proposalId, 'tx-binding-1', { success: true });
  first.startTimelock(proposal.proposalId, 100);
  nowRef.value = 1100;
  first.recordSimulation(proposal.proposalId, 'tx-binding-1', { success: true, phase: 'resimulation' });

  const recovered = new PersistentLifecycle(file, { clock: () => nowRef.value });
  const state = recovered.get(proposal.proposalId);
  assert.equal(state.state, 'RE_SIMULATED');
  assert.equal(state.transactionBindingHash, 'tx-binding-1');
  assert.equal(state.simulationBindingHash, 'tx-binding-1');
  assert.equal(state.proposal.proposalHash, proposal.proposalHash);
  assert.equal(recovered.verifyAuditChain(), true);
});

test('invalid transitions and stale versions are rejected', () => {
  const file = tempStore();
  const nowRef = { value: 0 };
  const { store, proposal } = createFlow(file, nowRef);
  assert.throws(() => store.transition(proposal.proposalId, 'APPROVED'), /INVALID_TRANSITION:CREATED->APPROVED/);
  const createdVersion = store.get(proposal.proposalId).version;
  store.transition(proposal.proposalId, 'HASHED', {}, createdVersion);
  assert.throws(() => store.transition(proposal.proposalId, 'BUILT', {}, createdVersion), /VERSION_CONFLICT/);
});

test('approval cannot bypass timelock or re-simulation', () => {
  const file = tempStore();
  const nowRef = { value: 0 };
  const { store, proposal: p } = createFlow(file, nowRef);
  store.transition(p.proposalId, 'HASHED');
  store.bindTransaction(p.proposalId, 'tx');
  store.recordSimulation(p.proposalId, 'tx', { success: true });
  store.startTimelock(p.proposalId, 100);
  assert.throws(() => store.approve(p.proposalId, 'approval-1'), /APPROVAL_REQUIRES_RESIMULATION/);
  nowRef.value = 100;
  store.recordSimulation(p.proposalId, 'tx', { success: true, phase: 'resimulation' });
  const approved = store.approve(p.proposalId, 'approval-1');
  assert.equal(approved.state, 'APPROVED');
  assert.equal(approved.approval.transactionBindingHash, 'tx');
  assert.equal(approved.approval.proposalHash, p.proposalHash);
});

test('simulation and approval remain bound to the exact transaction hash', () => {
  const file = tempStore();
  const nowRef = { value: 0 };
  const { store, proposal: p } = createFlow(file, nowRef);
  store.transition(p.proposalId, 'HASHED');
  store.bindTransaction(p.proposalId, 'tx-a');
  assert.throws(() => store.recordSimulation(p.proposalId, 'tx-b', { success: true }), /TRANSACTION_BINDING_MISMATCH/);
  store.recordSimulation(p.proposalId, 'tx-a', { success: true });
  store.startTimelock(p.proposalId, 1);
  nowRef.value = 1;
  assert.throws(() => store.recordSimulation(p.proposalId, 'tx-b', { success: true, phase: 'resimulation' }), /TRANSACTION_BINDING_MISMATCH/);
  store.recordSimulation(p.proposalId, 'tx-a', { success: true, phase: 'resimulation' });
  const approved = store.approve(p.proposalId, 'approval-exact');
  assert.equal(approved.approval.transactionBindingHash, 'tx-a');
});

test('tampered audit record is rejected during recovery', () => {
  const file = tempStore();
  const nowRef = { value: 0 };
  const { store, proposal: p } = createFlow(file, nowRef);
  store.transition(p.proposalId, 'HASHED');
  const lines = fs.readFileSync(file, 'utf8').trim().split('\n');
  const last = JSON.parse(lines[lines.length - 1]);
  last.nextState = 'APPROVED';
  lines[lines.length - 1] = JSON.stringify(last);
  fs.writeFileSync(file, `${lines.join('\n')}\n`);
  assert.throws(() => new PersistentLifecycle(file, { clock: () => nowRef.value }), /AUDIT_EVENT_TAMPERED/);
});

test('no router, signer, or broadcaster is introduced by proposal flow', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'daemon', 'proposal-flow.js'), 'utf8');
  assert.doesNotMatch(source, /RouterAdapter|sign_transaction|send_raw_transaction|private.?key|WALLET_PRIVATE_KEY/);
});
