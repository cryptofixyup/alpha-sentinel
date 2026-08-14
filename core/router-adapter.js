'use strict';

class BoundTransaction {
  constructor({ proposalId, payload, proposalHash }) {
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
    if (!proposalId || !proposalHash) throw new Error('PROPOSAL_ID_AND_HASH_REQUIRED');
    const snapshot = this.state.snapshot();
    const authorized = this.policy.authorize({ actor, transition: { type: 'bind', proposalId, proposalHash } });
    this.validator.validate({
      state: snapshot,
      transition: { type: 'set', expectedVersion: snapshot.version, payload: { key: 'bound', value: true } },
    });
    const transaction = this.build({ proposalId, proposalHash, payload, actor: authorized.actor });
    return new BoundTransaction({ proposalId, proposalHash, payload: transaction });
  }
}

module.exports = { RouterAdapter, BoundTransaction };
