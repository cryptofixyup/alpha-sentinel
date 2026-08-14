import { isValidatedTransition } from '../lifecycle/validator.js';

export class DurableState {
  #state;
  #version = 0;

  constructor(initialState) {
    this.#state = structuredClone(initialState);
  }

  read() {
    return Object.freeze({ state: structuredClone(this.#state), version: this.#version });
  }

  commit(validatedTransition) {
    if (!isValidatedTransition(validatedTransition)) {
      throw new Error('UNVALIDATED_TRANSITION');
    }
    if (validatedTransition.fromVersion !== this.#version) {
      throw new Error('STALE_VALIDATED_TRANSITION');
    }
    if (validatedTransition.fromState !== this.#state.state) {
      throw new Error('STATE_CHANGED_SINCE_VALIDATION');
    }
    if (validatedTransition.proposalId === this.#state.proposalId) {
      throw new Error('DUPLICATE_PROPOSAL');
    }

    this.#state = {
      ...this.#state,
      state: validatedTransition.target,
      proposalId: validatedTransition.proposalId,
    };
    this.#version += 1;
    return this.read();
  }
}
