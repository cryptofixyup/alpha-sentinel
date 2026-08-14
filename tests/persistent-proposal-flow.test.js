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

test('daemon proposal flow persists through restart', () => {
  const file = tempStore();
  let now = 1000;
  const first = new PersistentLifecycle(file, { clock: () => now });
  const flow = new ProposalFlow({ lifecycle: first, policy });
  const proposal = flow.propose({ asset: 'ETH', direction: 'LONG', sizePct: 0.05, calculatedEdge: 0.2, riskScore: 0.3 });
  assert.equal(first.get(proposal.proposalId).state, 'CREATED');
  first.transition(proposal.proposalId, 'HASHED');
  first.bindTransaction(proposal.proposalId, 'tx-binding-1');
  first.recordSimulation(proposal.proposalId, 'tx-binding-1', { success: true });
  first.startTimelock(proposal.proposalId, 100);
  now = 1100;
  first.recordSimulation(proposal.proposalId, 'tx-binding-1', { success: true, phase: 'resimulation' });

  const recovered = new PersistentLifecycle(file, { clock: () => now });
  const state = recovered.get(proposal.proposalId);
  assert.equal(state.state, 'RE_SIMULATED');
  assert.equal(state.transactionBindingHash, 'tx-binding-1');
  assert.equal(state.proposal.proposalHash, proposal.proposalHash);
  assert.equal(recovered.verifyAuditChain(), true);
});

test('approval cannot bypass timelock or re-simulation', () => {
  const file = tempStore();
  let now = 0;
  const store = new PersistentLifecycle(file, { clock: () => now });
  const flow = new ProposalFlow({ lifecycle: store, policy });
  const p = flow.propose({ asset: 'ETH', direction: 'LONG', sizePct: 0.01, calculatedEdge: 0.1, riskScore: 0.1 });
  store.transition(p.proposalId, 'HASHED');
  store.bindTransaction(p.proposalId, 'tx');
  store.recordSimulation(p.proposalId, 'tx', { success: true });
  store.startTimelock(p.proposalId, 100);
  assert.throws(() => store.approve(p.proposalId, 'approval-1'), /APPROVAL_REQUIRES_RESIMULATION/);
  now = 100;
  store.recordSimulation(p.proposalId, 'tx', { success: true, phase: 'resimulation' });
  assert.equal(store.approve(p.proposalId, 'approval-1').state, 'APPROVED');
});

test('tampered audit record is rejected during recovery', () => {
  const file = tempStore();
  let now = 0;
  const store = new PersistentLifecycle(file, { clock: () => now });
  const flow = new ProposalFlow({ lifecycle: store, policy });
  const p = flow.propose({ asset: 'ETH', direction: 'LONG', sizePct: 0.01, calculatedEdge: 0.1, riskScore: 0.1 });
  store.transition(p.proposalId, 'HASHED');
  const lines = fs.readFileSync(file, 'utf8').trim().split('\n');
  const last = JSON.parse(lines[lines.length - 1]);
  last.nextState = 'APPROVED';
  lines[lines.length - 1] = JSON.stringify(last);
  fs.writeFileSync(file, `${lines.join('\n')}\n`);
  assert.throws(() => new PersistentLifecycle(file, { clock: () => now }), /AUDIT_EVENT_TAMPERED/);
});

test('no router, signer, or broadcaster is introduced by proposal flow', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'daemon', 'proposal-flow.js'), 'utf8');
  assert.doesNotMatch(source, /RouterAdapter|sign_transaction|send_raw_transaction|private.?key|WALLET_PRIVATE_KEY/);
});
