'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { PersistentLifecycle } = require('../state/persistent-lifecycle');
const { ZernioRouterAdapter, CAPABILITIES, createZernioTransport, sha256, proposalHash } = require('../core/zernio-router-adapter');

function tempStore() { return path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'alpha-sentinel-zernio-')), 'lifecycle.log'); }
function makeProposal(overrides = {}) {
  const proposal = { proposalId: crypto.randomUUID(), content: 'Alpha Sentinel launch', platforms: [{ platform: 'twitter', accountId: 'acct-a' }], timezone: 'UTC', expiresAt: new Date(1000000).toISOString(), ...overrides };
  proposal.proposalHash = proposalHash(proposal); return proposal;
}
function approvedSetup() {
  const clock = { value: 0 }; const lifecycle = new PersistentLifecycle(tempStore(), { clock: () => clock.value }); const proposal = makeProposal();
  lifecycle.createProposal(proposal); lifecycle.transition(proposal.proposalId, 'HASHED'); lifecycle.bindTransaction(proposal.proposalId, 'tx-binding');
  lifecycle.recordSimulation(proposal.proposalId, 'tx-binding', { success: true }); lifecycle.startTimelock(proposal.proposalId, 100); clock.value = 100;
  lifecycle.recordSimulation(proposal.proposalId, 'tx-binding', { success: true, phase: 'resimulation' });
  lifecycle.recordValidation(proposal.proposalId, proposal.proposalHash, { valid: true, validationHash: sha256({ valid: true }) }); lifecycle.approve(proposal.proposalId, 'approval-1');
  return { lifecycle, proposal, clock };
}
function fakeTransport() {
  return {
    calls: [],
    async get(route, options) { this.calls.push(['GET', route, options]); if (route.startsWith('/posts/')) return { post: { _id: route.split('/').pop(), status: 'published' } }; return { accounts: [] }; },
    async post(route, options) {
      this.calls.push(['POST', route, options]);
      if (route === '/tools/validate/post') return { valid: true, message: 'No validation issues found.' };
      if (route === '/tools/validate/media') return { valid: true, type: 'image' };
      return { post: { _id: 'post-1', status: options.body?.scheduledFor ? 'scheduled' : options.body?.publishNow ? 'published' : 'draft' } };
    },
  };
}
function adapterFor(setup, transport = fakeTransport(), secret = 'webhook-secret') { return new ZernioRouterAdapter({ lifecycle: setup.lifecycle, transport, webhookSecret: secret, clock: () => setup.clock.value }); }

test('allowlist is exactly v1', () => assert.deepEqual(CAPABILITIES, ['readAccounts','validatePost','validateMedia','createDraft','scheduleApproved','executeApproved','getExecutionStatus','ingestWebhook']));
test('LLM cannot publish directly through a raw Zernio operation', () => { const a = adapterFor(approvedSetup()); assert.equal(typeof a.publishNow, 'undefined'); assert.equal(typeof a.post, 'undefined'); assert.equal(Object.prototype.hasOwnProperty.call(a, 'transport'), false); assert.ok(!Object.keys(a).some((key) => /key|token|secret|transport/i.test(key))); });
test('LLM cannot obtain the Zernio credential from the adapter', () => { const setup = approvedSetup(); const key = `sk_${'a'.repeat(64)}`; const transport = createZernioTransport({ apiKey: key, fetchImpl: async () => new Response('{}', { status: 200 }) }); const a = new ZernioRouterAdapter({ lifecycle: setup.lifecycle, transport, webhookSecret: 'webhook-secret' }); assert.equal(Object.prototype.hasOwnProperty.call(a, 'apiKey'), false); assert.equal(Object.prototype.hasOwnProperty.call(a, 'transport'), false); assert.equal(JSON.stringify(a).includes(key), false); });
test('unapproved proposal cannot execute', async () => { const clock = { value: 0 }; const lifecycle = new PersistentLifecycle(tempStore(), { clock: () => clock.value }); const proposal = makeProposal(); lifecycle.createProposal(proposal); const a = new ZernioRouterAdapter({ lifecycle, transport: fakeTransport(), webhookSecret: 'webhook-secret', clock: () => clock.value }); await assert.rejects(a.executeApproved(proposal), /PROPOSAL_NOT_APPROVED/); });
test('modified proposal cannot execute', async () => { const s = approvedSetup(); const p = { ...s.proposal, content: 'MUTATED' }; p.proposalHash = proposalHash(p); await assert.rejects(adapterFor(s).executeApproved(p), /APPROVED_PROPOSAL_MISMATCH/); });
test('wrong account cannot execute', async () => { const s = approvedSetup(); const p = { ...s.proposal, platforms: [{ platform: 'twitter', accountId: 'acct-b' }] }; p.proposalHash = proposalHash(p); await assert.rejects(adapterFor(s).executeApproved(p), /APPROVED_PROPOSAL_MISMATCH/); });
test('wrong platform cannot execute', async () => { const s = approvedSetup(); const p = { ...s.proposal, platforms: [{ platform: 'linkedin', accountId: 'acct-a' }] }; p.proposalHash = proposalHash(p); await assert.rejects(adapterFor(s).executeApproved(p), /APPROVED_PROPOSAL_MISMATCH/); });
test('expired proposal cannot execute', async () => { const s = approvedSetup(); s.clock.value = 1000001; await assert.rejects(adapterFor(s).executeApproved(s.proposal), /PROPOSAL_EXPIRED/); });
test('timelock cannot be bypassed', async () => { const p = makeProposal(); const lifecycle = { get: () => ({ proposal: p, state: 'APPROVED', timelockUntil: 200, approval: { proposalHash: p.proposalHash }, validationValid: true, validationBindingHash: 'v' }) }; const a = new ZernioRouterAdapter({ lifecycle, transport: fakeTransport(), webhookSecret: 'webhook-secret', clock: () => 100 }); await assert.rejects(a.executeApproved(p), /TIMELOCK_ACTIVE/); });
test('failed validation cannot execute', async () => { const s = approvedSetup(); s.lifecycle.recordValidation(s.proposal.proposalId, s.proposal.proposalHash, { valid: false, validationHash: sha256({ valid: false }) }); await assert.rejects(adapterFor(s).executeApproved(s.proposal), /VALIDATION_REQUIRED/); });
test('duplicate webhook cannot duplicate state transition', () => { const s = approvedSetup(); const a = adapterFor(s); const rawBody = JSON.stringify({ id: 'evt-1', event: 'post.published', postId: 'post-1' }); const signature = crypto.createHmac('sha256', 'webhook-secret').update(rawBody).digest('hex'); const first = a.ingestWebhook({ rawBody, signature }); const second = a.ingestWebhook({ rawBody, signature }); assert.equal(first.duplicate, false); assert.equal(second.duplicate, true); assert.equal(s.lifecycle.get(s.proposal.proposalId).state, 'APPROVED'); });
test('invalid webhook signature cannot alter state', () => { const s = approvedSetup(); const a = adapterFor(s); const before = s.lifecycle.get(s.proposal.proposalId); assert.throws(() => a.ingestWebhook({ rawBody: JSON.stringify({ id: 'evt-2', event: 'post.published' }), signature: 'invalid' }), /INVALID_WEBHOOK_SIGNATURE/); assert.deepEqual(s.lifecycle.get(s.proposal.proposalId), before); });
test('validation endpoints are limited to Zernio preflight routes', async () => { const s = approvedSetup(); const transport = fakeTransport(); const a = adapterFor(s, transport); await a.validatePost(s.proposal); await a.validateMedia({ url: 'https://example.com/image.jpg' }); assert.deepEqual(transport.calls.map((call) => call[1]), ['/tools/validate/post','/tools/validate/media']); });
test('scheduleApproved rejects schedule drift after approval', async () => { const s = approvedSetup(); const p = { ...s.proposal, scheduledFor: new Date(2000000).toISOString() }; p.proposalHash = proposalHash(p); await assert.rejects(adapterFor(s).scheduleApproved(p), /APPROVED_PROPOSAL_MISMATCH/); });
test('execution uses x-request-id idempotency and publishNow only behind approval', async () => { const s = approvedSetup(); const transport = fakeTransport(); const result = await adapterFor(s, transport).executeApproved(s.proposal); const call = transport.calls.find((entry) => entry[1] === '/posts'); assert.equal(result.post.status, 'published'); assert.equal(call[2].body.publishNow, true); assert.match(call[2].requestId, /^[0-9a-f-]{36}$/); });
