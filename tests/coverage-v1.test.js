'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { evaluateUnapprovedExecution } = require('../coverage/contract');
const { recordFailure, regressionTestSource } = require('../coverage/failure-recorder');
const {
  runUnapprovedExecutionProbe,
  vulnerableProbeExecutor,
  hardenedProbeExecutor
} = require('../coverage/probe');

test('coverage v1 captures the first boundary failure deterministically', () => {
  const observation = runUnapprovedExecutionProbe(vulnerableProbeExecutor);
  const evaluation = evaluateUnapprovedExecution(observation);

  assert.equal(evaluation.status, 'VIOLATION');
  assert.equal(evaluation.contract, 'UNAPPROVED_EXECUTION');
  assert.equal(evaluation.actual.executionReached, true);
  assert.equal(evaluation.expected.executionReached, false);
});

test('failure is converted into a stable fixture and regression source', () => {
  const rootDir = fs.mkdtempSync(path.join(os.tmpdir(), 'alpha-sentinel-coverage-'));
  const observation = runUnapprovedExecutionProbe(vulnerableProbeExecutor);
  const evaluation = evaluateUnapprovedExecution(observation);
  const failure = recordFailure({
    rootDir,
    contract: evaluation.contract,
    probe: 'unapproved-execution-001',
    observation,
    evaluation
  });

  assert.ok(failure);
  assert.match(failure.id, /^[a-f0-9]{64}$/);
  assert.ok(fs.existsSync(failure.fixturePath));

  const generated = regressionTestSource(failure.fixture);
  assert.match(generated, new RegExp(failure.id));
  assert.match(generated, /UNAPPROVED_EXECUTION/);
  assert.match(generated, /executionReached/);
});

test('hardened control prevents the captured failure class', () => {
  const observation = runUnapprovedExecutionProbe(hardenedProbeExecutor);
  const evaluation = evaluateUnapprovedExecution(observation);

  assert.equal(observation.executionReached, false);
  assert.equal(evaluation.status, 'PASS');
});

test('coverage layer remains observational and exposes no authorization API', () => {
  const coverage = require('../coverage/contract');
  const recorder = require('../coverage/failure-recorder');
  assert.equal(typeof coverage.authorize, 'undefined');
  assert.equal(typeof recorder.authorize, 'undefined');
});
