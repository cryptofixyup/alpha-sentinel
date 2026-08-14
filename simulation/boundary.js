'use strict';

class SimulationBoundary {
  constructor(simulator = null) {
    this.simulator = simulator || (() => ({ ok: true }));
  }

  simulate(boundTransaction) {
    if (!boundTransaction || boundTransaction.kind !== 'BoundTransaction') {
      throw new Error('BOUND_TRANSACTION_REQUIRED');
    }
    const result = this.simulator(boundTransaction);
    if (!result || result.ok !== true) throw new Error('SIMULATION_FAILED');
    return Object.freeze({ ok: true, result: structuredClone(result) });
  }
}

module.exports = { SimulationBoundary };
