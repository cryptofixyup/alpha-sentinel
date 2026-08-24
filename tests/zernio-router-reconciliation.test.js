'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { PersistentLifecycle } = require('../state/persistent-lifecycle');
const { ZernioRouterAdapter, proposalHash, sha256, deterministicRequestId } = require('../core/zernio-router-adapter');

function tempStore() { return path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'alpha-sentinel-zernio-reconcile-')), 'lifecycle.log'); }
function makeProposal(overrides = {}) {
  const proposal = { proposalId: crypto.randomUUID(), content: 'Alpha Sentinel launch', platforms: [{ platform: 'twitter', accountId: 'acct-a' }], timezone: 'UTC', expiresAt: new Date(1000000).toISOString(), ...overrides };
  proposal.proposalHash = proposalHash(proposal);
  return proposal;
}
function setup() {
  const clock = { value: 0 };
  const file = tempStore();
  const lifecycle = new PersistentLifecycle(file, { clock: () => clock.value });
  const proposal = makeProposal();
  lifecycle.createProposal(proposal);
  lifecycle.transition(proposal.proposalId, 'HASHED');
  lifecycle.bindTransaction(proposal.proposalId, 'tx-binding');
  lifecycle.recordSimulation(proposal.proposalId, 'tx-binding', { success: true });
  lifecycle.startTimelock(proposal.proposalId, 100);
  clock.value = 100;
  lifecycle.recordSimulation(proposal.proposalId, 'tx-binding', { success: true, phase: 'resimulation' });
  lifecycle.recordValidation(proposal.proposalId, proposal.proposalHash, { valid: true, validationHash: sha256({ valid: true }) });
  lifecycle.approve(proposal.proposalId, 'approval-1');
  return { clock, file, lifecycle, proposal };
}
function transport() {
  return {
    calls: [],
    async get(route) { this.calls.push(['GET', route]); return { post: { _id: route.split('/').pop(), status: 'published' } }; },
    async post(route, options) {
      this.calls.push(['POST', route, options]);
      return { post: { _id: 'post-1', status: options.body?.scheduledFor ? 'scheduled' : options.body?.publishNow ? 'published' : 'draft' } };
    },
  };
}
function adapter(s, t = transport()) { return new ZernioRouterAdapter({ lifecycle: s.lifecycle, transport: t, webhookSecret: 'webhook-secret', clock: () => s.clock.value }); }
function signed(raw) { return crypto.createHmac('sha256', 'webhook-secret').update(raw).digest('hex'); }

async function execute(s) {
  const a = adapter(s);
  const result = await a.executeApproved(s.proposal);
  assert.equal(result.post._id, 'post-1');
  return a;
}

test('executeApproved durably binds the Zernio post ID and request ID', async () => {
  const s = setup();
  const t = transport();
  await adapter(s, t).executeApproved(s.proposal);
  const record = s.lifecycle.get(s.proposal.proposalId);
  assert.equal(record.state, 'BROADCAST');
  assert.deepEqual(record.externalExecution, {
    postId: 'post-1',
    requestId: deterministicRequestId(s.proposal.proposalHash),
    mode: 'publish',
    status: 'published',
    proposalHash: s.proposal.proposalHash,
  });
});

test('published webhook advances BROADCAST to VERIFIED exactly once', async () => {
  const s = setup();
  const a = await execute(s);
  const raw = JSON.stringify({ id: 'evt-published-1', event: 'post.published', post: { id: 'post-1', status: 'published' } });
  const first = a.ingestWebhook({ rawBody: raw, signature: signed(raw) });
  assert.equal(first.duplicate, false);
  assert.equal(first.state, 'VERIFIED');
  const afterFirst = s.lifecycle.get(s.proposal.proposalId);
  const version = afterFirst.version;
  const second = a.ingestWebhook({ rawBody: raw, signature: signed(raw) });
  assert.equal(second.duplicate, true);
  assert.equal(s.lifecycle.get(s.proposal.proposalId).version, version);
  assert.equal(s.lifecycle.verifyAuditChain(), true);
});

test('external post correlation survives lifecycle restart', async () => {
  const s = setup();
  const a = await execute(s);
  const before = s.lifecycle.get(s.proposal.proposalId);
  const restarted = new PersistentLifecycle(s.file, { clock: () => s.clock.value });
  const a2 = new ZernioRouterAdapter({ lifecycle: restarted, transport: transport(), webhookSecret: 'webhook-secret', clock: () => s.clock.value });
  const raw = JSON.stringify({ id: 'evt-restart-1', event: 'post.published', post: { id: before.externalExecution.postId, status: 'published' } });
  const result = a2.ingestWebhook({ rawBody: raw, signature: signed(raw) });
  assert.equal(result.proposalId, s.proposal.proposalId);
  assert.equal(restarted.get(s.proposal.proposalId).state, 'VERIFIED');
  assert.equal(restarted.verifyAuditChain(), true);
});

test('webhook for an unknown post cannot mutate an approved proposal', () => {
  const s = setup();
  const a = adapter(s);
  const before = s.lifecycle.get(s.proposal.proposalId);
  const raw = JSON.stringify({ id: 'evt-wrong-post', event: 'post.published', post: { id: 'attacker-post', status: 'published' } });
  const result = a.ingestWebhook({ rawBody: raw, signature: signed(raw) });
  assert.equal(result.correlated, false);
  assert.deepEqual(s.lifecycle.get(s.proposal.proposalId), before);
});

test('post.failed webhook durably rejects a broadcast execution', async () => {
  const s = setup();
  const a = await execute(s);
  const raw = JSON.stringify({ id: 'evt-failed-1', event: 'post.failed', post: { id: 'post-1', status: 'failed' } });
  const result = a.ingestWebhook({ rawBody: raw, signature: signed(raw) });
  assert.equal(result.state, 'REJECTED');
  assert.equal(s.lifecycle.get(s.proposal.proposalId).state, 'REJECTED');
});

test('scheduled execution is correlated before publication', async () => {
  const s = setup();
  const proposal = { ...s.proposal, scheduledFor: new Date(2000000).toISOString() };
  proposal.proposalHash = proposalHash(proposal);
  s.lifecycle.get(s.proposal.proposalId);
  // Rebuild the lifecycle record with the scheduled proposal hash for this isolated test.
  const file = tempStore();
  const lifecycle = new PersistentLifecycle(file, { clock: () => s.clock.value });
  lifecycle.createProposal(proposal);
  lifecycle.transition(proposal.proposalId, 'HASHED');
  lifecycle.bindTransaction(proposal.proposalId, 'tx-binding');
  lifecycle.recordSimulation(proposal.proposalId, 'tx-binding', { success: true });
  lifecycle.startTimelock(proposal.proposalId, 100);
  lifecycle.recordSimulation(proposal.proposalId, 'tx-binding', { success: true, phase: 'resimulation' });
  lifecycle.recordValidation(proposal.proposalId, proposal.proposalHash, { valid: true, validationHash: sha256({ valid: true }) });
  lifecycle.approve(proposal.proposalId, 'approval-1');
  const local = { ...s, lifecycle };
  const a = adapter(local);
  await a.scheduleApproved(proposal);
  assert.equal(lifecycle.get(proposal.proposalId).state, 'BROADCAST');
});
