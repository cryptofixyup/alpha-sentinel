'use strict';

/** DurableState performs mutation only. It has no actor/authorization knowledge. */
class DurableState {
  constructor(initial = {}) {
    this._data = structuredClone(initial);
    this._version = 0;
  }

  get version() { return this._version; }

  snapshot() {
    return Object.freeze({ version: this._version, data: structuredClone(this._data) });
  }

  apply(validatedTransition) {
    if (!validatedTransition || validatedTransition.kind !== 'ValidatedTransition') {
      throw new Error('VALIDATED_TRANSITION_REQUIRED');
    }
    if (validatedTransition.expectedVersion !== this._version) {
      throw new Error('VERSION_CONFLICT');
    }

    this._data = this._reduce(this._data, validatedTransition);
    this._version += 1;
    return this.snapshot();
  }

  _reduce(data, transition) {
    const next = structuredClone(data);
    if (transition.type === 'set') {
      if (typeof transition.payload.key !== 'string') throw new Error('INVALID_SET_KEY');
      next[transition.payload.key] = transition.payload.value;
      return next;
    }
    throw new Error('UNKNOWN_TRANSITION');
  }
}

module.exports = { DurableState };
