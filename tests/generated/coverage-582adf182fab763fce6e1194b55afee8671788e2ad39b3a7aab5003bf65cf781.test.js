'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { evaluateUnapprovedExecution } = require('../../coverage/contract');

const fixture = require('../../fixtures/coverage/failures/582adf182fab763fce6e1194b55afee8671788e2ad39b3a7aab5003bf65cf781.json');

test('regression 582adf182fab763fce6e1194b55afee8671788e2ad39b3a7aab5003bf65cf781', () => {
  const evaluation = evaluateUnapprovedExecution(fixture.observation);
  assert.equal(evaluation.status, 'VIOLATION');
  assert.equal(evaluation.contract, fixture.contract);
});
