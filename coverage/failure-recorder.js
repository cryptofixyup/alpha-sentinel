'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

function failureId(failure) {
  return crypto.createHash('sha256').update(canonicalJson(failure)).digest('hex');
}

function recordFailure({ rootDir, contract, probe, observation, evaluation }) {
  if (evaluation.status !== 'VIOLATION') return null;

  const fixture = {
    schema_version: 1,
    contract,
    probe,
    observation,
    expected: evaluation.expected,
    actual: evaluation.actual
  };

  const id = failureId(fixture);
  const stored = { ...fixture, failure_id: id };
  const dir = path.join(rootDir, 'fixtures', 'coverage', 'failures');
  fs.mkdirSync(dir, { recursive: true });

  const fixturePath = path.join(dir, `${id}.json`);
  fs.writeFileSync(fixturePath, `${JSON.stringify(stored, null, 2)}\n`, 'utf8');

  return { id, fixturePath, fixture: stored };
}

function regressionTestSource(fixture) {
  const encoded = JSON.stringify(fixture, null, 2);
  return `'use strict';\n\nconst test = require('node:test');\nconst assert = require('node:assert/strict');\nconst { evaluateUnapprovedExecution } = require('../../coverage/contract');\n\nconst fixture = ${encoded};\n\ntest(${JSON.stringify(`regression ${fixture.failure_id}`)}, () => {\n  const evaluation = evaluateUnapprovedExecution(fixture.observation);\n  assert.equal(evaluation.status, 'VIOLATION');\n});\n`;
}

module.exports = { canonicalJson, failureId, recordFailure, regressionTestSource };
