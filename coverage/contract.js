'use strict';

/**
 * Deterministic contract evaluation for observable execution behavior.
 * The coverage layer has no authorization authority; it only evaluates evidence.
 */
function evaluateUnapprovedExecution(observation) {
  if (!observation || typeof observation !== 'object') {
    throw new TypeError('OBSERVATION_REQUIRED');
  }

  const unauthorized = observation.approvalState !== 'APPROVED';
  const executionReached = observation.executionReached === true;

  return {
    contract: 'UNAPPROVED_EXECUTION',
    status: unauthorized && executionReached ? 'VIOLATION' : 'PASS',
    expected: { executionReached: false },
    actual: { executionReached },
    evidence: {
      approvalState: observation.approvalState,
      executionReached
    }
  };
}

module.exports = { evaluateUnapprovedExecution };
