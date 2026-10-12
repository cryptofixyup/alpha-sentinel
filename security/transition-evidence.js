'use strict';

const crypto = require('node:crypto');
const { stable, signingBytes } = require('./signed-result-verifier');

function transactionDigest(tx) {
  if (!tx || tx.kind !== 'BoundTransaction') throw new Error('BOUND_TRANSACTION_REQUIRED');
  return crypto.createHash('sha256').update(stable(tx)).digest('hex');
}

class TransitionEvidenceVerifier {
  #executionKey;
  #receiptKey;
  #clock;
  constructor({ executionPublicKey, verificationPublicKey, evidenceClock = Date.now } = {}) {
    this.#executionKey = executionPublicKey;
    this.#receiptKey = verificationPublicKey;
    this.#clock = evidenceClock;
    if (executionPublicKey && verificationPublicKey) {
      const exportKey = key => (key.type === 'public' ? key : crypto.createPublicKey(key)).export({ type: 'spki', format: 'der' });
      if (exportKey(executionPublicKey).equals(exportKey(verificationPublicKey))) {
        throw new Error('INDEPENDENT_VERIFICATION_KEY_REQUIRED');
      }
    }
  }

  verify(evidence, current, kind) {
    const key = kind === 'execution' ? this.#executionKey : this.#receiptKey;
    if (!key) throw new Error('EVIDENCE_PUBLIC_KEY_REQUIRED');
    if (!evidence || typeof evidence !== 'object') throw new Error('SIGNED_EVIDENCE_REQUIRED');
    const proof = structuredClone(evidence);
    const expectedStatus = kind === 'execution' ? 'EXECUTED' : 'VERIFIED';
    if (proof.kind !== kind || proof.status !== expectedStatus) throw new Error('EVIDENCE_STATUS_MISMATCH');
    const now = this.#clock();
    if (!Number.isSafeInteger(proof.timestamp) || proof.timestamp > now || now - proof.timestamp > 300000) {
      throw new Error('EVIDENCE_STALE');
    }
    const precedingTimestamp = kind === 'execution'
      ? current.metadata.approvedAt
      : current.metadata.executionEvidence?.timestamp;
    if (!Number.isSafeInteger(precedingTimestamp) || precedingTimestamp < 0) {
      throw new Error('EVIDENCE_TRANSITION_TIME_REQUIRED');
    }
    // Millisecond timestamps may coincide, but signed outcomes cannot predate their prerequisite.
    if (proof.timestamp < precedingTimestamp) throw new Error('EVIDENCE_PRECEDES_TRANSITION');
    if (proof.proposalId !== current.proposalId || proof.proposalHash !== current.metadata.proposalHash ||
        proof.transactionDigest !== transactionDigest(current.metadata.boundTransaction)) {
      throw new Error('EVIDENCE_TRANSACTION_MISMATCH');
    }
    if (typeof proof.txHash !== 'string' || !proof.txHash.trim()) throw new Error('EVIDENCE_TX_HASH_REQUIRED');
    if (kind === 'receipt' && proof.txHash !== current.metadata.executionEvidence?.txHash) {
      throw new Error('EVIDENCE_EXECUTION_MISMATCH');
    }
    let valid = false;
    try {
      valid = crypto.verify(null, signingBytes(proof), key, Buffer.from(proof.signature, 'base64url'));
    } catch { /* Invalid proof fails closed below. */ }
    if (!valid) throw new Error('EVIDENCE_SIGNATURE_INVALID');
    return Object.freeze(proof);
  }
}

module.exports = { TransitionEvidenceVerifier, transactionDigest };
