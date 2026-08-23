'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

/** Append-only, hash-chained audit log with an independent terminal checkpoint. */
class AuditLog {
  constructor(filePath) {
    this.filePath = path.resolve(filePath);
    this.checkpointPath = `${this.filePath}.checkpoint`;
    fs.mkdirSync(path.dirname(this.filePath), { recursive: true });

    const auditExists = fs.existsSync(this.filePath);
    const checkpointExists = fs.existsSync(this.checkpointPath);
    if (!auditExists && !checkpointExists) {
      fs.closeSync(fs.openSync(this.filePath, 'a'));
      this._writeCheckpoint({ sequence: -1, hash: 'GENESIS' });
    } else if (auditExists !== checkpointExists) {
      throw new Error('AUDIT_CHECKPOINT_MISSING');
    }
  }

  _records() {
    const text = fs.readFileSync(this.filePath, 'utf8');
    return text.trim() ? text.trim().split('\n').map(JSON.parse) : [];
  }

  _checkpoint() {
    try {
      return JSON.parse(fs.readFileSync(this.checkpointPath, 'utf8'));
    } catch {
      throw new Error('AUDIT_CHECKPOINT_INVALID');
    }
  }

  _writeAll(fd, data, truncateTo = null) {
    const buffer = Buffer.isBuffer(data) ? data : Buffer.from(data);
    let offset = 0;
    try {
      while (offset < buffer.length) {
        const written = fs.writeSync(fd, buffer, offset, buffer.length - offset, null);
        if (!Number.isInteger(written) || written <= 0) throw new Error('AUDIT_WRITE_INCOMPLETE');
        offset += written;
      }
    } catch (error) {
      if (truncateTo !== null) {
        try { fs.ftruncateSync(fd, truncateTo); } catch { /* preserve original write error */ }
      }
      throw error;
    }
  }

  _writeCheckpoint(checkpoint) {
    const data = `${JSON.stringify(checkpoint)}\n`;
    const fd = fs.openSync(this.checkpointPath, 'w');
    try {
      this._writeAll(fd, data, 0);
      fs.fsyncSync(fd);
    } finally {
      fs.closeSync(fd);
    }
  }

  verify() {
    let previous = 'GENESIS';
    const records = this._records();
    for (const record of records) {
      const { hash, ...body } = record;
      if (record.previousHash !== previous) throw new Error('AUDIT_CHAIN_BROKEN');
      const expected = crypto.createHash('sha256').update(JSON.stringify(body)).digest('hex');
      if (hash !== expected) throw new Error('AUDIT_RECORD_TAMPERED');
      previous = hash;
    }

    const checkpoint = this._checkpoint();
    const expectedSequence = records.length - 1;
    if (checkpoint.sequence !== expectedSequence || checkpoint.hash !== previous) {
      throw new Error('AUDIT_TERMINAL_CHECKPOINT_MISMATCH');
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
    try {
      const initialSize = fs.fstatSync(fd).size;
      this._writeAll(fd, record, initialSize);
      fs.fsyncSync(fd);
    } finally {
      fs.closeSync(fd);
    }
    this._writeCheckpoint({ sequence: body.sequence, hash });
    return Object.freeze({ ...body, hash });
  }

  records() { this.verify(); return this._records(); }
}

module.exports = { AuditLog };
