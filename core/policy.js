'use strict';

/** Sole authorization boundary for security-critical transitions. */
class Policy {
  constructor(authorizer) {
    if (typeof authorizer !== 'function') throw new TypeError('authorizer must be a function');
    this.authorizer = authorizer;
  }

  authorize({ actor, transition }) {
    // Classification must be supplied by a trusted ingress, never by model text.
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
