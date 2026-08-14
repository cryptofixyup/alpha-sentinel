'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

/**
 * DurableState is the mutation boundary. It has no actor/authorization knowledge.
 *
 * When journalPath is supplied, every accepted ValidatedTransition is persisted as
 * an append-only, hash-chained record before in-memory state is advanced. Startup
 * replays and verifies the complete journal, so a restart cannot silently lose or
 * alter an accepted transition.
 */
class DurableState {
  constructor(initial = {}, { journalPath = null } = {}) {
    this._data = structuredClone(initial);
    this._version = 0;
    this._journalPath = journalPath ? path.resolve(journalPath) : null;
    this._lastRecordHash = 'GENESIS';
    this._records = [];

    if (this._journalPath) this._recover();
  }

  get version() { return this._version; }

  snapshot() {
    return Object.freeze({ version: this._version, data: structuredClone(this._data) });
  }

  audit() {
    return this._records.map(record => Object.freeze(structuredClone(record)));
  }

  apply(validatedTransition) {
    if (!validatedTransition || validatedTransition.kind !== 'ValidatedTransition') {
      throw new Error('VALIDATED_TRANSITION_REQUIRED');
    }
    if (validatedTransition.expectedVersion !== this._version) {
      throw new Error('VERSION_CONFLICT');
    }

    const nextData = this._reduce(this._data, validatedTransition);
    const nextVersion = this._version + 1;

    if (this._journalPath) {
      const record = this._buildRecord(validatedTransition, nextVersion);
      this._append(record);
      this._records.push(record);
      this._lastRecordHash = record.recordHash;
    }

    this._data = nextData;
    this._version = nextVersion;
    return this.snapshot();
  }

  _buildRecord(transition, nextVersion) {
    const body = {
      sequence: this._records.length + 1,
      versionBefore: this._version,
      versionAfter: nextVersion,
      transition: {
        kind: transition.kind,
        type: transition.type,
        payload: structuredClone(transition.payload ?? {}),
        expectedVersion: transition.expectedVersion,
      },
      previousHash: this._lastRecordHash,
    };
    const recordHash = hashCanonical(body);
    return Object.freeze({ ...body, recordHash });
  }

  _append(record) {
    fs.mkdirSync(path.dirname(this._journalPath), { recursive: true });
    const line = `${JSON.stringify(record)}\n`;
    const fd = fs.openSync(this._journalPath, 'a');
    try {
      fs.writeSync(fd, line, null, 'utf8');
      fs.fsyncSync(fd);
    } finally {
      fs.closeSync(fd);
    }
  }

  _recover() {
    if (!fs.existsSync(this._journalPath)) return;
    const content = fs.readFileSync(this._journalPath, 'utf8');
    if (content.length === 0) return;

    const lines = content.split('\n');
    if (lines[lines.length - 1] !== '') throw new Error('CORRUPT_JOURNAL_TRAILING_DATA');
    lines.pop();

    for (const line of lines) {
      let record;
      try {
        record = JSON.parse(line);
      } catch {
        throw new Error('CORRUPT_JOURNAL_RECORD');
      }
      this._verifyRecord(record);
      const transition = record.transition;
      this._data = this._reduce(this._data, transition);
      this._version = record.versionAfter;
      this._lastRecordHash = record.recordHash;
      this._records.push(Object.freeze(record));
    }
  }

  _verifyRecord(record) {
    if (!record || typeof record !== 'object') throw new Error('CORRUPT_JOURNAL_RECORD');
    if (record.sequence !== this._records.length + 1) throw new Error('AUDIT_SEQUENCE_INVALID');
    if (record.versionBefore !== this._version) throw new Error('AUDIT_VERSION_INVALID');
    if (record.versionAfter !== this._version + 1) throw new Error('AUDIT_VERSION_INVALID');
    if (record.previousHash !== this._lastRecordHash) throw new Error('AUDIT_CHAIN_BROKEN');
    if (!record.transition || record.transition.kind !== 'ValidatedTransition') {
      throw new Error('AUDIT_TRANSITION_INVALID');
    }
    if (record.transition.expectedVersion !== record.versionBefore) {
      throw new Error('AUDIT_TRANSITION_VERSION_INVALID');
    }
    const { recordHash, ...body } = record;
    if (recordHash !== hashCanonical(body)) throw new Error('AUDIT_RECORD_HASH_INVALID');
  }

  _reduce(data, transition) {
    const next = structuredClone(data);
    if (transition.type === 'set') {
      if (!transition.payload || typeof transition.payload.key !== 'string') {
        throw new Error('INVALID_SET_KEY');
      }
      next[transition.payload.key] = structuredClone(transition.payload.value);
      return next;
    }
    throw new Error('UNKNOWN_TRANSITION');
  }
}

function hashCanonical(value) {
  return crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
}

module.exports = { DurableState, hashCanonical };
