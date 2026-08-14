'use strict';

const { BoundTransaction } = require('../core/router-adapter');

class SimulationBoundary {
  simulate(boundTransaction) {
    if (!(boundTransaction instanceof BoundTransaction) || boundTransaction.kind !== 'BoundTransaction') {
      throw new Error('BOUND_TRANSACTION_REQUIRED');
    }
    return Object.freeze({
      proposalHash: boundTransaction.proposalHash,
      transition: boundTransaction.validatedTransition,
      simulated: true,
    });
  }
}

module.exports = { SimulationBoundary };
