'use strict';

/**
 * Synthetic probe only. It never calls a live service or privileged executor.
 * The injected executor is deliberately allowed to model a boundary failure.
 */
function runUnapprovedExecutionProbe(executor) {
  if (typeof executor !== 'function') throw new TypeError('EXECUTOR_REQUIRED');

  const proposal = {
    proposalId: 'coverage-probe-001',
    approvalState: 'TIMED_WAIT',
    action: 'executeApproved'
  };

  const result = executor(proposal);

  return {
    approvalState: proposal.approvalState,
    executionReached: result && result.executionReached === true,
    action: proposal.action,
    proposalId: proposal.proposalId
  };
}

function vulnerableProbeExecutor() {
  // Deliberately models the class of failure the harness must catch.
  return { executionReached: true };
}

function hardenedProbeExecutor(proposal) {
  return { executionReached: proposal.approvalState === 'APPROVED' };
}

module.exports = { runUnapprovedExecutionProbe, vulnerableProbeExecutor, hardenedProbeExecutor };
