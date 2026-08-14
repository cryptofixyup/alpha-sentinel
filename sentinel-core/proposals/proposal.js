function deepFreeze(value) {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const child of Object.values(value)) deepFreeze(child);
  }
  return value;
}

export function createProposal({ id, actor, expectedVersion, payload }) {
  if (!id || !actor || !Number.isInteger(expectedVersion) || expectedVersion < 0) throw new Error('INVALID_PROPOSAL');
  return deepFreeze({ id, actor, expectedVersion, payload: structuredClone(payload) });
}
