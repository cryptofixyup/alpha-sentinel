export class InMemoryDurableState {
  #state;
  #version;

  constructor(initialState) {
    this.#state = structuredClone(initialState);
    this.#version = 0;
  }

  read() { return Object.freeze({ state: structuredClone(this.#state), version: this.#version }); }

  commit(expectedVersion, nextState) {
    if (expectedVersion !== this.#version) throw new Error('STALE_STATE');
    this.#state = structuredClone(nextState);
    this.#version += 1;
    return this.read();
  }
}
