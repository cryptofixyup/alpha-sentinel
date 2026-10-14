"""Local reference enforcement gate. HMAC is a shared-secret prototype, not an interoperable signature standard."""
from __future__ import annotations
import hashlib
import hmac
import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


@dataclass(frozen=True)
class ScopeContract:
    allowed_tools: frozenset[str]
    tenant: str
    def permits(self, tool: str, tenant: str) -> bool:
        return bool(self.tenant) and tenant == self.tenant and tool in self.allowed_tools


class AuthorityError(PermissionError):
    pass


class ControlPlane:
    def __init__(self, key: bytes, db_path: str | Path, scope: ScopeContract):
        if len(key) < 32:
            raise ValueError('Control-plane HMAC key must be >=32 bytes')
        self._key = key
        self.scope = scope
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None, timeout=10)
        self._db.execute('PRAGMA busy_timeout=10000')
        self._db.execute('CREATE TABLE IF NOT EXISTS grants (nonce TEXT PRIMARY KEY, status TEXT NOT NULL, outcome TEXT, revoked INTEGER NOT NULL DEFAULT 0)')

    def issue(self, tenant: str, tool: str, args: dict, ttl: int = 60) -> dict:
        if not self.scope.permits(tool, tenant) or not 1 <= ttl <= 3600:
            raise AuthorityError('Scope denied')
        body = {'v': 1, 'tenant': tenant, 'tool': tool, 'args_hash': digest(args), 'nonce': uuid.uuid4().hex, 'expires': int(time.time()) + ttl}
        signature = hmac.new(self._key, canonical(body), hashlib.sha256).hexdigest()
        return {'body': body, 'signature': signature}

    def revoke(self, nonce: str) -> None:
        with self._lock:
            self._db.execute('INSERT INTO grants(nonce,status,revoked) VALUES (?, ?, 1) ON CONFLICT(nonce) DO UPDATE SET revoked=1', (nonce, 'REVOKED'))

    def execute(self, grant: dict, tenant: str, tool: str, args: dict, executor: Callable[..., Any]) -> Any:
        try:
            body, signature = grant['body'], grant['signature']
            valid_signature = hmac.compare_digest(hmac.new(self._key, canonical(body), hashlib.sha256).hexdigest(), signature)
            valid_binding = (body['v'] == 1 and body['tenant'] == tenant and body['tool'] == tool and body['args_hash'] == digest(args))
            valid_time = int(time.time()) < body['expires']
            nonce = body['nonce']
            if not isinstance(nonce, str) or len(nonce) != 32:
                raise ValueError('Invalid nonce')
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise AuthorityError('Malformed grant') from exc
        if not (valid_signature and valid_binding and valid_time and self.scope.permits(tool, tenant)):
            raise AuthorityError('Authorization denied')
        with self._lock:
            try:
                self._db.execute('BEGIN IMMEDIATE')
                self._db.execute('INSERT INTO grants(nonce,status) VALUES (?,?)', (nonce, 'RESERVED'))
                self._db.execute('COMMIT')
            except sqlite3.IntegrityError as exc:
                self._db.execute('ROLLBACK')
                raise AuthorityError('Grant replayed or revoked') from exc
            except BaseException:
                self._db.execute('ROLLBACK')
                raise
        # A crash after reservation leaves RESERVED: fail-closed; never automatically replay.
        try:
            result = executor(**args)
        except BaseException as exc:
            self._record(nonce, 'UNKNOWN', {'error_type': type(exc).__name__})
            raise
        self._record(nonce, 'COMPLETED', {'result_sha256': digest(str(result))})
        return result

    def _record(self, nonce: str, status: str, outcome: dict) -> None:
        with self._lock:
            self._db.execute('UPDATE grants SET status=?, outcome=? WHERE nonce=?', (status, canonical(outcome).decode(), nonce))

    def evidence(self, nonce: str) -> tuple | None:
        return self._db.execute('SELECT status,outcome,revoked FROM grants WHERE nonce=?', (nonce,)).fetchone()

    def close(self):
        self._db.close()