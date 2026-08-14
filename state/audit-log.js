'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

/** Append-only, hash-chained audit log. Existing records are never rewritten. */
class AuditLog {
  constructor(filePath) {
    this.filePath = path.resolve(filePath);
    fs.mkdirSync(path.dirname(this.filePath), { recursive: true });
    if (!fs.existsSync(this.filePath)) fs.closeSync(fs.openSync(this.filePath, 'a'));
  }

  _records() {
    const text = fs.readFileSync(this.filePath, 'utf8');
    return text.trim() ? text.trim().split('\n').map(JSON.parse) : [];
  }

  verify() {
    let previous = 'GENESIS';
    for (const record of this._records()) {
      const { hash, ...body } = record;
      if (record.previousHash !== previous) throw new Error('AUDIT_CHAIN_BROKEN');
      const expected = crypto.createHash('sha256').update(JSON.stringify(body)).digest('hex');
      if (hash !== expected) throw new Error('AUDIT_RECORD_TAMPERED');
      previous = hash;
    }
    return true;
  }

  append({ lifecycleId, from, to, event, data = {} }) {
    this.verify();
    const records = this._records();
    const previousHash = records.length ? records[records.length - 1].hash : 'GENESIS';
    const body = Object.freeze({
      sequence: records.length,
      timestamp: Date.now(),
      lifecycleId,
      from,
      to,
      event,
      data: structuredClone(data),
      previousHash,
    });
    const hash = crypto.createHash('sha256').update(JSON.stringify(body)).digest('hex');
    const record = JSON.stringify({ ...body, hash }) + '\n';
    const fd = fs.openSync(this.filePath, 'a');
    try { fs.writeSync(fd, record); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
    return Object.freeze({ ...body, hash });
  }

  records() { this.verify(); return this._records(); }
}

module.exports = { AuditLog };
