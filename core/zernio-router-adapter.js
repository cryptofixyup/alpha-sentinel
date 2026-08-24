'use strict';

const crypto = require('node:crypto');

const BASE_URL = 'https://zernio.com/api/v1';
const CAPABILITIES = Object.freeze([
  'readAccounts',
  'validatePost',
  'validateMedia',
  'createDraft',
  'scheduleApproved',
  'executeApproved',
  'getExecutionStatus',
  'ingestWebhook',
]);

function stable(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`;
  return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stable(value[key])}`).join(',')}}`;
}

function sha256(value) {
  return crypto.createHash('sha256').update(stable(value)).digest('hex');
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function proposalHash(proposal) {
  const unsigned = clone(proposal);
  delete unsigned.proposalHash;
  return sha256(unsigned);
}

function assertProposal(proposal) {
  if (!proposal || typeof proposal !== 'object') throw new Error('INVALID_PROPOSAL');
  for (const key of ['proposalId', 'proposalHash', 'content', 'platforms']) {
    if (proposal[key] === undefined) throw new Error(`PROPOSAL_FIELD_REQUIRED:${key}`);
  }
  if (!Array.isArray(proposal.platforms) || proposal.platforms.length === 0) throw new Error('TARGETS_REQUIRED');
  if (proposalHash(proposal) !== proposal.proposalHash) throw new Error('PROPOSAL_HASH_MISMATCH');
}

function targetSet(proposal) {
  return proposal.platforms.map(({ platform, accountId }) => ({ platform, accountId }));
}

function postBody(proposal, mode) {
  const body = {
    content: proposal.content,
    mediaItems: proposal.mediaItems,
    platforms: targetSet(proposal),
    timezone: proposal.timezone || 'UTC',
  };
  if (proposal.title !== undefined) body.title = proposal.title;
  if (proposal.tags) body.tags = proposal.tags;
  if (proposal.hashtags) body.hashtags = proposal.hashtags;
  if (proposal.mentions) body.mentions = proposal.mentions;
  if (proposal.metadata) body.metadata = proposal.metadata;
  if (mode === 'draft') body.isDraft = true;
  if (mode === 'schedule') body.scheduledFor = proposal.scheduledFor;
  if (mode === 'publish') body.publishNow = true;
  return body;
}

function createZernioTransport({ apiKey, fetchImpl = globalThis.fetch, baseUrl = BASE_URL } = {}) {
  if (typeof apiKey !== 'string' || apiKey.length === 0) throw new TypeError('ZERNIO_API_KEY_REQUIRED');
  if (typeof fetchImpl !== 'function') throw new TypeError('FETCH_REQUIRED');

  const request = async (method, path, { query, body, requestId } = {}) => {
    const url = new URL(`${baseUrl}${path}`);
    if (query) for (const [key, value] of Object.entries(query)) if (value !== undefined) url.searchParams.set(key, String(value));
    const headers = { Authorization: `Bearer ${apiKey}` };
    if (body !== undefined) headers['content-type'] = 'application/json';
    if (requestId) headers['x-request-id'] = requestId;
    const response = await fetchImpl(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    const text = await response.text();
    let data;
    try { data = text ? JSON.parse(text) : {}; } catch { data = { raw: text }; }
    if (!response.ok) {
      const error = new Error(data?.error || `ZERNIO_HTTP_${response.status}`);
      error.status = response.status;
      error.details = data;
      throw error;
    }
    return data;
  };

  return Object.freeze({
    get: (path, options) => request('GET', path, options),
    post: (path, options) => request('POST', path, options),
  });
}

class ZernioRouterAdapter {
  #lifecycle;
  #transport;
  #webhookSecret;
  #clock;
  #processedWebhookIds = new Set();
  #webhookEvents = new Map();

  constructor({ lifecycle, transport, webhookSecret, clock = () => Date.now() }) {
    if (!lifecycle || typeof lifecycle.get !== 'function') throw new TypeError('LIFECYCLE_REQUIRED');
    if (!transport || typeof transport.get !== 'function' || typeof transport.post !== 'function') throw new TypeError('TRANSPORT_REQUIRED');
    if (typeof webhookSecret !== 'string' || webhookSecret.length === 0) throw new TypeError('WEBHOOK_SECRET_REQUIRED');
    this.#lifecycle = lifecycle;
    this.#transport = transport;
    this.#webhookSecret = webhookSecret;
    this.#clock = clock;
  }

  readAccounts({ profileId, platform, status } = {}) {
    return this.#transport.get('/accounts', { query: { profileId, platform, status } });
  }

  async validatePost(proposal) {
    assertProposal(proposal);
    const result = await this.#transport.post('/tools/validate/post', {
      body: { content: proposal.content, platforms: targetSet(proposal), mediaItems: proposal.mediaItems },
    });
    if (typeof this.#lifecycle.recordValidation !== 'function') throw new Error('VALIDATION_EVIDENCE_STORE_REQUIRED');
    const validationHash = sha256({ kind: 'zernio-post-validation', proposalHash: proposal.proposalHash, result });
    this.#lifecycle.recordValidation(proposal.proposalId, proposal.proposalHash, { valid: result.valid === true, validationHash });
    return result;
  }

  validateMedia({ url }) {
    if (typeof url !== 'string' || !url) throw new Error('MEDIA_URL_REQUIRED');
    return this.#transport.post('/tools/validate/media', { body: { url } });
  }

  async createDraft(proposal) {
    assertProposal(proposal);
    return this.#transport.post('/posts', { body: postBody(proposal, 'draft'), requestId: crypto.randomUUID() });
  }

  async scheduleApproved(proposal) {
    this.#assertApproved(proposal);
    if (typeof proposal.scheduledFor !== 'string' || !proposal.scheduledFor) throw new Error('SCHEDULE_REQUIRED');
    return this.#transport.post('/posts', { body: postBody(proposal, 'schedule'), requestId: crypto.randomUUID() });
  }

  async executeApproved(proposal) {
    this.#assertApproved(proposal);
    return this.#transport.post('/posts', { body: postBody(proposal, 'publish'), requestId: crypto.randomUUID() });
  }

  getExecutionStatus(postId) {
    if (typeof postId !== 'string' || !postId) throw new Error('POST_ID_REQUIRED');
    return this.#transport.get(`/posts/${encodeURIComponent(postId)}`);
  }

  ingestWebhook({ rawBody, signature, eventId }) {
    if (typeof rawBody !== 'string') throw new Error('RAW_BODY_REQUIRED');
    if (typeof signature !== 'string' || !signature) throw new Error('WEBHOOK_SIGNATURE_REQUIRED');
    const expected = crypto.createHmac('sha256', this.#webhookSecret).update(rawBody).digest('hex');
    const a = Buffer.from(expected, 'utf8');
    const b = Buffer.from(signature, 'utf8');
    if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) throw new Error('INVALID_WEBHOOK_SIGNATURE');

    let payload;
    try { payload = JSON.parse(rawBody); } catch { throw new Error('INVALID_WEBHOOK_JSON'); }
    const id = eventId || payload.id;
    if (typeof id !== 'string' || !id) throw new Error('WEBHOOK_EVENT_ID_REQUIRED');
    if (this.#processedWebhookIds.has(id)) return { accepted: true, duplicate: true, id };

    this.#processedWebhookIds.add(id);
    this.#webhookEvents.set(id, Object.freeze({ id, event: payload.event, payload: clone(payload), receivedAt: this.#clock() }));
    return { accepted: true, duplicate: false, id, event: payload.event };
  }

  #assertApproved(proposal) {
    assertProposal(proposal);
    const record = this.#lifecycle.get(proposal.proposalId);
    if (record.proposal.proposalHash !== proposal.proposalHash) throw new Error('APPROVED_PROPOSAL_MISMATCH');
    if (record.state !== 'APPROVED') throw new Error('PROPOSAL_NOT_APPROVED');
    if (!record.approval || record.approval.proposalHash !== proposal.proposalHash) throw new Error('APPROVAL_BINDING_MISMATCH');
    if (record.timelockUntil !== null && this.#clock() < record.timelockUntil) throw new Error('TIMELOCK_ACTIVE');
    if (proposal.expiresAt !== undefined && this.#clock() >= Date.parse(proposal.expiresAt)) throw new Error('PROPOSAL_EXPIRED');
    if (record.validationValid !== true || !record.validationBindingHash) throw new Error('VALIDATION_REQUIRED');
  }
}

module.exports = { ZernioRouterAdapter, CAPABILITIES, createZernioTransport, stable, sha256, proposalHash };
