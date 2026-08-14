export function createProposal({ id, actor, expectedVersion, payload }) {
  if (!id || !actor || !Number.isInteger(expectedVersion) || expectedVersion < 0) {
    throw new Error('INVALID_PROPOSAL');
  }
  return Object.freeze({ id, actor, expectedVersion, payload: structuredClone(payload) });
}
