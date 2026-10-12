'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { Policy } = require('../core/policy');
const { Validator } = require('../core/validator');
const { DurableState } = require('../state/store');
const { AuthorizationDaemon } = require('../core/daemon');
const { RouterAdapter } = require('../core/router-adapter');
const { SimulationBoundary } = require('../simulation/boundary');
const { signResult } = require('../security/signed-result-verifier');
const { transactionDigest } = require('../security/transition-evidence');

function setup() {
  const execution = crypto.generateKeyPairSync('ed25519');
  const receipt = crypto.generateKeyPairSync('ed25519');
  const policy = new Policy(actor => actor === 'operator');
  const validator = new Validator();
  const state = new DurableState();
  const routerAdapter = new RouterAdapter({ policy, validator, state,
    build: ({ proposalId, proposalHash, payload }) => ({ proposalId, proposalHash, payload }) });
  const d = new AuthorizationDaemon({ policy, validator, state, routerAdapter,
    simulationBoundary: new SimulationBoundary(() => ({ ok: true })),
    executionPublicKey: execution.publicKey, verificationPublicKey: receipt.publicKey,
    evidenceClock: () => 1000000 });
  d.propose({ proposalId: 'p', proposalHash: 'hash-p', payload: { action: 'test' } });
  d.authorize({ actor: 'operator' });
  d.validate({ actor: 'operator' });
  const tx = d.bind({ actor: 'operator' });
  d.simulate({ actor: 'operator' });
  d.enterTimelock({ actor: 'operator', unlockAt: 1000 });
  d.resimulate({ actor: 'operator', now: 1000 });
  d.approve({ actor: 'operator' });
  const proof = (kind, overrides = {}, key) => signResult({ kind,
    status: kind === 'execution' ? 'EXECUTED' : 'VERIFIED', timestamp: 1000000,
    proposalId: 'p', proposalHash: 'hash-p', transactionDigest: transactionDigest(tx),
    txHash: '0x1234', ...overrides }, key || (kind === 'execution' ? execution : receipt).privateKey);
  return { d, proof, execution, receipt };
}

test('signed execution and independent signed receipt permit terminal transitions', () => {
  const { d, proof } = setup();
  d.execute({ actor: 'operator', evidence: proof('execution') });
  assert.equal(d.snapshot().lifecycle, 'EXECUTED');
  d.verify({ actor: 'operator', evidence: proof('receipt') });
  assert.equal(d.snapshot().lifecycle, 'VERIFIED');
  assert.equal(d.snapshot().metadata.verificationEvidence.txHash, '0x1234');
});

test('direct lifecycle access cannot skip signed terminal evidence', () => {
  const { d } = setup();
  assert.throws(() => d.lifecycle.advance({ actor: 'operator', to: 'EXECUTED' }), /SIGNED_EVIDENCE_REQUIRED/);
  assert.equal(d.snapshot().lifecycle, 'APPROVED');
});

for (const [name, overrides, error] of [
  ['wrong proposal', { proposalId: 'other' }, /EVIDENCE_TRANSACTION_MISMATCH/],
  ['wrong transaction', { transactionDigest: '0'.repeat(64) }, /EVIDENCE_TRANSACTION_MISMATCH/],
  ['stale evidence', { timestamp: 699999 }, /EVIDENCE_STALE/],
  ['future evidence', { timestamp: 1000001 }, /EVIDENCE_STALE/],
  ['failed execution', { status: 'FAILED' }, /EVIDENCE_STATUS_MISMATCH/],
]) test(`execution rejects ${name} without state mutation`, () => {
  const { d, proof } = setup();
  assert.throws(() => d.execute({ actor: 'operator', evidence: proof('execution', overrides) }), error);
  assert.equal(d.snapshot().lifecycle, 'APPROVED');
});

test('forged evidence and execution-signed receipts fail closed', () => {
  const { d, proof, execution } = setup();
  const forged = { ...proof('execution'), signature: 'invalid' };
  assert.throws(() => d.execute({ actor: 'operator', evidence: forged }), /EVIDENCE_SIGNATURE_INVALID/);
  d.execute({ actor: 'operator', evidence: proof('execution') });
  assert.throws(() => d.verify({ actor: 'operator', evidence: proof('receipt', {}, execution.privateKey) }), /EVIDENCE_SIGNATURE_INVALID/);
  assert.throws(() => d.verify({ actor: 'operator', evidence: proof('receipt', { txHash: 'another' }) }), /EVIDENCE_EXECUTION_MISMATCH/);
  assert.equal(d.snapshot().lifecycle, 'EXECUTED');
});

test('execution and verification authorities must use independent keys', () => {
  const { TransitionEvidenceVerifier } = require('../security/transition-evidence');
  const { publicKey } = crypto.generateKeyPairSync('ed25519');
  assert.throws(() => new TransitionEvidenceVerifier({ executionPublicKey: publicKey, verificationPublicKey: publicKey }), /INDEPENDENT_VERIFICATION_KEY_REQUIRED/);
});
