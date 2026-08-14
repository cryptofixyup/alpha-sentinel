'use strict';

const crypto = require('node:crypto');
const { AuditLog } = require('./audit-log');

const TERMINAL = new Set(['REJECTED', 'EXPIRED', 'BROADCAST', 'VERIFIED']);
const ALLOWED = Object.freeze({
  CREATED: ['HASHED', 'REJECTED'], HASHED: ['SIMULATED', 'REJECTED'],
  SIMULATED: ['TIMELOCKED', 'APPROVED', 'REJECTED'],
  TIMELOCKED: ['RESIMULATION_REQUIRED', 'EXPIRED'],
  RESIMULATION_REQUIRED: ['RESIMULATED', 'EXPIRED'],
  RESIMULATED: ['APPROVED', 'REJECTED'],
  APPROVED: ['SIGNED', 'REJECTED'], SIGNED: ['BROADCAST', 'REJECTED'],
  BROADCAST: ['VERIFIED', 'REJECTED'], REJECTED: [], EXPIRED: [], VERIFIED: [],
});

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map(k => `${JSON.stringify(k)}:${canonical(value[k])}`).join(',')}}`;
  return JSON.stringify(value);
}

class PersistentLifecycle {
  constructor({ filePath, timelockSeconds = 172800, now = () => Math.floor(Date.now() / 1000) }) {
    this.audit = new AuditLog(filePath); this.timelockSeconds = timelockSeconds; this.now = now; this._state = new Map(); this._recover();
  }

  _recover() {
    for (const event of this.audit.records()) {
      const prior = this._state.get(event.lifecycleId);
      const expectedVersion = prior ? prior.version + 1 : 0;
      if (event.data.version !== expectedVersion) throw new Error('LIFECYCLE_VERSION_BROKEN');
      if (prior && (event.from !== prior.state || !ALLOWED[prior.state]?.includes(event.to))) throw new Error('LIFECYCLE_HISTORY_INVALID');
      this._state.set(event.lifecycleId, { version: event.data.version, state: event.to, proposalHash: event.data.proposalHash ?? prior?.proposalHash, transactionHash: event.data.transactionHash ?? prior?.transactionHash, unlockAt: event.data.unlockAt ?? prior?.unlockAt });
    }
  }

  create({ lifecycleId, proposal, proposalHash }) {
    if (this._state.has(lifecycleId)) throw new Error('LIFECYCLE_EXISTS');
    const expected = crypto.createHash('sha256').update(canonical(proposal)).digest('hex');
    if (!proposalHash) throw new Error('PROPOSAL_HASH_REQUIRED');
    if (expected !== proposalHash) throw new Error('PROPOSAL_HASH_MISMATCH');
    return this._transition(lifecycleId, 'GENESIS', 'CREATED', { proposalHash });
  }

  transition(lifecycleId, to, data = {}) {
    const current = this._require(lifecycleId);
    if (TERMINAL.has(current.state)) throw new Error('LIFECYCLE_TERMINAL');
    if (!ALLOWED[current.state]?.includes(to)) throw new Error('INVALID_STATE_TRANSITION');
    if (to === 'APPROVED' && current.state === 'SIMULATED' && current.unlockAt && current.unlockAt > this.now()) throw new Error('TIMELOCK_ACTIVE');
    if (to === 'APPROVED' && current.state === 'RESIMULATED' && data.transactionHash !== current.transactionHash) throw new Error('RESIMULATION_BINDING_MISMATCH');
    return this._transition(lifecycleId, current.state, to, data);
  }

  timelock(lifecycleId, transactionHash) {
    const current = this._require(lifecycleId);
    if (current.state !== 'SIMULATED') throw new Error('SIMULATION_REQUIRED');
    return this._transition(lifecycleId, current.state, 'TIMELOCKED', { transactionHash, unlockAt: this.now() + this.timelockSeconds });
  }

  requireResimulation(lifecycleId) {
    const current = this._require(lifecycleId);
    if (current.state !== 'TIMELOCKED') throw new Error('TIMELOCK_REQUIRED');
    if (this.now() < current.unlockAt) throw new Error('TIMELOCK_ACTIVE');
    return this._transition(lifecycleId, current.state, 'RESIMULATION_REQUIRED', {});
  }

  get(lifecycleId) { return Object.freeze(structuredClone(this._require(lifecycleId))); }
  _require(id) { const state = this._state.get(id); if (!state) throw new Error('LIFECYCLE_NOT_FOUND'); return state; }

  _transition(id, from, to, data) {
    const current = this._state.get(id); const version = current ? current.version + 1 : 0;
    const event = this.audit.append({ lifecycleId: id, from, to, event: `STATE_${to}`, data: { ...structuredClone(data), version, proposalHash: data.proposalHash ?? current?.proposalHash, transactionHash: data.transactionHash ?? current?.transactionHash, unlockAt: data.unlockAt ?? current?.unlockAt } });
    this._state.set(id, { version, state: to, proposalHash: event.data.proposalHash, transactionHash: event.data.transactionHash, unlockAt: event.data.unlockAt });
    return this.get(id);
  }
}

module.exports = { PersistentLifecycle, ALLOWED, canonical };
