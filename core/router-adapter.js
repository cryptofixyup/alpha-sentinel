'use strict';

class BoundTransaction {
  constructor({ proposalId, payload, proposalHash }) {
    if (!proposalId || typeof proposalId !== 'string') throw new Error('PROPOSAL_ID_REQUIRED');
    if (!proposalHash || typeof proposalHash !== 'string') throw new Error('PROPOSAL_HASH_REQUIRED');
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
      throw new Error('MALFORMED_TRANSACTION_ENVELOPE');
    }
    this.kind = 'BoundTransaction';
    this.proposalId = proposalId;
    this.payload = Object.freeze(structuredClone(payload));
    this.proposalHash = proposalHash;
    Object.freeze(this);
  }
}

/** Transaction construction only. No signing, wallet, or broadcast capability. */
class RouterAdapter {
  constructor({ policy, validator, state, build }) {
    if (!policy || typeof policy.authorize !== 'function') throw new TypeError('policy required');
    if (!validator || typeof validator.validate !== 'function') throw new TypeError('validator required');
    if (!state || typeof state.snapshot !== 'function') throw new TypeError('state required');
    if (typeof build !== 'function') throw new TypeError('build required');
    this.policy = policy;
    this.validator = validator;
    this.state = state;
    this.build = build;
  }

  construct({ actor, proposalId, proposalHash, payload }) {
    if (!proposalId || typeof proposalId !== 'string' || !proposalHash || typeof proposalHash !== 'string') {
      throw new Error('PROPOSAL_ID_AND_HASH_REQUIRED');
    }
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
      throw new Error('MALFORMED_TRANSACTION_ENVELOPE');
    }

    const snapshot = this.state.snapshot();
    const lifecycle = snapshot.data.lifecycle;
    if (!lifecycle || lifecycle.state !== 'APPROVED') throw new Error('ROUTER_BIND_REQUIRES_APPROVAL');
    if (lifecycle.proposalId !== proposalId) throw new Error('PROPOSAL_ID_MISMATCH');
    if (lifecycle.metadata?.proposalHash !== proposalHash) throw new Error('PROPOSAL_HASH_MISMATCH');

    const authorized = this.policy.authorize({ actor, transition: { type: 'bind', proposalId, proposalHash } });
    this.validator.validate({
      state: snapshot,
      transition: { type: 'set', expectedVersion: snapshot.version, payload: { key: 'bound', value: true } },
    });

    const transaction = this.build({ proposalId, proposalHash, payload, actor: authorized.actor });
    if (!transaction || typeof transaction !== 'object' || Array.isArray(transaction)) {
      throw new Error('MALFORMED_TRANSACTION_ENVELOPE');
    }
    return new BoundTransaction({ proposalId, proposalHash, payload: transaction });
  }
}

module.exports = { RouterAdapter, BoundTransaction };
