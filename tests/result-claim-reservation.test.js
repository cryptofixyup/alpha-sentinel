'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { signResult, verifySignedResult, loadSeenResultIds } = require('../security/signed-result-verifier');

function fixture(t, claimedId) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'result-reservation-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const journal = path.join(dir, 'results.log');
  const claims = `${journal}.claims`;
  fs.mkdirSync(claims);
  const claim = path.join(claims, `${crypto.createHash('sha256').update(claimedId).digest('hex')}.claim`);
  fs.writeFileSync(claim, ''); // Window between exclusive open and payload write.
  const { privateKey, publicKey } = crypto.generateKeyPairSync('ed25519');
  const result = signResult({ resultId: 'target', proposalId: 'p', proposalHash: 'h',
    postId: 'post', requestId: 'req', platform: 'twitter', accountId: 'a',
    status: 'published', timestamp: 1 }, privateKey);
  const lifecycle = { get: () => ({ proposal: { proposalHash: 'h',
    platforms: [{ platform: 'twitter', accountId: 'a' }] },
    externalExecution: { postId: 'post', requestId: 'req' } }) };
  return { journal, claim, input: { result, publicKey, lifecycle, now: () => 1, resultJournalPath: journal } };
}

test('existing empty reservation for this result denies as duplicate without mutation', t => {
  const { journal, claim, input } = fixture(t, 'target');
  assert.throws(() => verifySignedResult(input), { message: 'RESULT_DUPLICATE' });
  assert.equal(fs.readFileSync(claim, 'utf8'), '');
  assert.equal(fs.existsSync(journal), false);
});

test('unrelated empty claim and standalone recovery still fail closed', t => {
  const { journal, claim, input } = fixture(t, 'other');
  assert.throws(() => verifySignedResult(input), { message: 'RESULT_CLAIM_INVALID' });
  assert.throws(() => loadSeenResultIds(journal), { message: 'RESULT_CLAIM_INVALID' });
  assert.equal(fs.readFileSync(claim, 'utf8'), '');
  assert.equal(fs.existsSync(journal), false);
});
