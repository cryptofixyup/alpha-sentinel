export const DECISIONS = Object.freeze({ ALLOW: 'ALLOW', DENY: 'DENY' });

export function createPolicy({ actors = [], operations = [], now = 0 } = {}) {
  return Object.freeze({
    actors: new Set(actors),
    operations: new Set(operations),
    now,
  });
}

export function authorize({ proposal, state, policy }) {
  if (!proposal || !state || !policy) return DECISIONS.DENY;
  if (proposal.expectedVersion !== state.version) return DECISIONS.DENY;
  if (!policy.actors.has(proposal.actor)) return DECISIONS.DENY;
  if (!policy.operations.has(proposal.payload?.operation)) return DECISIONS.DENY;
  if (Number.isInteger(proposal.payload?.expiresAt) && proposal.payload.expiresAt <= policy.now) {
    return DECISIONS.DENY;
  }
  return DECISIONS.ALLOW;
}
