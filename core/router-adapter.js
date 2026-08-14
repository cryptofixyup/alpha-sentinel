'use strict';

const crypto = require('node:crypto');

class RouterAdapter {
  constructor({ policy, validator, state }) {
    this.policy = policy;
    this.validator = validator;
    this.state = state;
  }

  construct(proposal) {
    if (!proposal || typeof proposal !== 'object') throw new Error('INVALID_PROPOSAL');
    const canonical = JSON.stringify({ actor: proposal.actor, transition: proposal.transition });
    const expectedHash = crypto.createHash('sha256').update(canonical).digest('hex');
    if (proposal.hash !== expectedHash) throw new Error('PROPOSAL_HASH_MISMATCH');

    this.policy.authorize({ actor: proposal.actor, transition: proposal.transition });
    const validated = this.validator.validate({ state: this.state.snapshot(), transition: proposal.transition });

    return new BoundTransaction({
      proposalHash: proposal.hash,
      validatedTransition: validated,
    });
  }
}

class BoundTransaction {
  constructor({ proposalHash, validatedTransition }) {
    this.kind = 'BoundTransaction';
    this.proposalHash = proposalHash;
    this.validatedTransition = validatedTransition;
    Object.freeze(this);
  }
}

module.exports = { RouterAdapter, BoundTransaction };
