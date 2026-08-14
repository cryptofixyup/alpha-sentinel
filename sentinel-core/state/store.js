import { applyTransition } from '../lifecycle/machine.js';

export class DurableState {
  #state;
  #version = 0;

  constructor(initialState) {
    this.#state = structuredClone(initialState);
  }

  read() {
    return Object.freeze({ state: structuredClone(this.#state), version: this.#version });
  }

  transition(proposal, to, policy) {
    const current = { ...this.#state, version: this.#version };
    const next = applyTransition({ current, proposal, to, policy });
    this.#state = structuredClone(next);
    this.#version += 1;
    return this.read();
  }
}
