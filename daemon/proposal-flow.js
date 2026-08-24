'use strict';

const crypto = require('node:crypto');
const { PersistentLifecycle } = require('../state/persistent-lifecycle');

function canonicalize(value) {
  return JSON.stringify(value, Object.keys(value).sort());
}

function sha256(value) {
  return crypto.createHash('sha256').update(canonicalize(value)).digest('hex');
}

function freezeProposal(input) {
  const proposal = Object.freeze({
    proposalId: input.proposalId,
    createdAt: input.createdAt,
    asset: input.asset,
    direction: input.direction,
    sizePct: input.sizePct,
    policyVersion: input.policyVersion,
    riskScore: input.riskScore,
    calculatedEdge: input.calculatedEdge,
    metadata: Object.freeze({ ...(input.metadata || {}) })
  });
  return Object.freeze({ ...proposal, proposalHash: sha256(proposal) });
}

/**
 * Actual daemon proposal boundary.
 * It deliberately terminates at HASHED until a separately configured router exists.
 */
class ProposalFlow {
  constructor({ lifecycle, policy }) {
    if (!(lifecycle instanceof PersistentLifecycle)) throw new TypeError('PERSISTENT_LIFECYCLE_REQUIRED');
    if (typeof policy !== 'function') throw new TypeError('DETERMINISTIC_POLICY_REQUIRED');
    this.lifecycle = lifecycle;
    this.policy = policy;
  }

  propose({ asset, direction, sizePct, calculatedEdge, riskScore, metadata = {}, policyVersion = 'policy-v1' }) {
    const decision = this.policy({ asset, direction, sizePct, calculatedEdge, riskScore });
    if (!decision || decision.approved !== true) throw new Error('POLICY_DENIED');

    const proposal = freezeProposal({
      proposalId: crypto.randomUUID(),
      createdAt: Date.now(), asset, direction, sizePct,
      policyVersion, riskScore, calculatedEdge, metadata
    });

    this.lifecycle.createProposal(proposal);
    return proposal;
  }

  get(proposalId) {
    return this.lifecycle.get(proposalId);
  }
}

module.exports = { ProposalFlow, canonicalize, sha256 };
