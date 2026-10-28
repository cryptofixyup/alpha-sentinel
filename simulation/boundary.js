'use strict';

class SimulationBoundary {
  /**
   * @param {function} simulator - Required trusted simulator. It must accept a
   * BoundTransaction and return an object whose `ok` property is exactly true.
   * Missing configuration, invalid results, cloning failures, and thrown errors
   * all fail closed.
   */
  constructor(simulator) {
    if (typeof simulator !== 'function') {
      throw new TypeError('simulator function required');
    }
    this.simulator = simulator;
  }

  simulate(boundTransaction) {
    if (!boundTransaction || boundTransaction.kind !== 'BoundTransaction') {
      throw new Error('BOUND_TRANSACTION_REQUIRED');
    }

    try {
      const result = this.simulator(boundTransaction);
      if (!result || typeof result !== 'object' || result.ok !== true) {
        throw new Error('SIMULATION_FAILED');
      }
      const clonedResult = structuredClone(result);
      return Object.freeze({ ok: true, result: clonedResult });
    } catch {
      throw new Error('SIMULATION_FAILED');
    }
  }
}

module.exports = { SimulationBoundary };
