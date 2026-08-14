import { applyTransition } from '../lifecycle/machine.js';

export class DurableState {
  #state;
  #version = 0;
  #authorizedActors;

  constructor(initialState, authorizedActors) {
    this.#state = structuredClone(initialState);
    this.#authorizedActors = new Set(authorizedActors);
  }

  read() {
    return Object.freeze({ state: structuredClone(this.#state), version: this.#version });
  }

  transition(proposal, to) {
    if (!this.#authorizedActors.has(proposal.actor)) throw new Error('UNAUTHORIZED_ACTOR');
    const current = { ...this.#state, version: this.#version };
    const next = applyTransition({ current, proposal, to });
    this.#state = structuredClone(next);
    this.#version += 1;
    return this.read();
  }
}
