export const DECISIONS = Object.freeze({ ALLOW: 'ALLOW', DENY: 'DENY' });

export function authorize({ proposal, state, rules }) {
  if (!proposal || !state || !rules) return DECISIONS.DENY;
  if (proposal.expectedVersion !== state.version) return DECISIONS.DENY;
  if (rules.actors && !rules.actors.has(proposal.actor)) return DECISIONS.DENY;
  if (rules.operations && !rules.operations.has(proposal.payload?.operation)) return DECISIONS.DENY;
  if (Number.isInteger(proposal.payload?.expiresAt) && proposal.payload.expiresAt <= rules.now) return DECISIONS.DENY;
  return DECISIONS.ALLOW;
}

export function createPolicy({ actors = [], operations = [], now = 0 } = {}) {
  return Object.freeze({
    actors: new Set(actors),
    operations: new Set(operations),
    now,
  });
}
