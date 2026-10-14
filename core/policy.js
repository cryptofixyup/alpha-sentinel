'use strict';

/** Sole authorization boundary for security-critical transitions. */
class Policy {
  constructor(authorizer) {
    if (typeof authorizer !== 'function') throw new TypeError('authorizer must be a function');
    this.authorizer = authorizer;
  }

  authorize({ actor, transition }) {
    // Principal classification must come from a trusted caller, never model text.
    if (actor && typeof actor === 'object' &&
        (actor.kind === 'agent' || actor.kind === 'model')) {
      throw new Error('POLICY_DENIED');
    }
    const allowed = this.authorizer(actor, transition);
    if (!allowed) throw new Error('POLICY_DENIED');
    return Object.freeze({ actor, transition });
  }
}

module.exports = { Policy };
