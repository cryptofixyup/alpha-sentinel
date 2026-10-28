"""Durable, transactional state for execution reservations and settlement idempotency.

Use a shared persistent SQLite file only when all workers share the same filesystem.
Multi-host deployments must use a transactional shared database implementation with
the same semantics; an in-memory database is never suitable for production.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
import sqlite3
import threading
from typing import Iterator


_BROADCAST_STATES = {
    "IN_FLIGHT",
    "BROADCAST",
    "RECONCILIATION_REQUIRED",
    "CONFIRMED",
    "FAILED",
}


def _integer(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


class SQLiteExecutionState:
    """SQLite-backed atomic reservations and broadcast journal.

    Reservation safety depends on every worker using the same database. The
    observed exposure baseline is initialized once and updated only by the
    explicit reconciliation method after an authoritative portfolio snapshot.
    Reservations remain counted until failed/reconciled or reflected in that
    snapshot. Ambiguous broadcasts are never silently claimable for resubmission.
    """

    def __init__(self, path: str) -> None:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("persistent execution-state database path required")
        if path == ":memory:" and os.environ.get("ALPHA_SENTINEL_ENV", "").strip().lower() == "production":
            raise RuntimeError("production requires persistent shared execution-state storage")
        if path != ":memory:":
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            try:
                fd = os.open(path, flags, 0o600)
            except FileExistsError:
                os.chmod(path, 0o600)
            else:
                os.close(fd)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
        self._db.execute("PRAGMA busy_timeout=30000")
        self._db.execute("PRAGMA synchronous=FULL")
        if path != ":memory:":
            self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS portfolio_baselines (
                portfolio_id TEXT PRIMARY KEY,
                exposure_bps INTEGER NOT NULL CHECK (exposure_bps >= 0)
            );
            CREATE TABLE IF NOT EXISTS exposure_reservations (
                portfolio_id TEXT NOT NULL,
                request_id TEXT NOT NULL,
                size_bps INTEGER NOT NULL CHECK (size_bps > 0),
                state TEXT NOT NULL CHECK (state IN ('RESERVED','RECONCILIATION_REQUIRED','COMMITTED','RELEASED')),
                PRIMARY KEY (portfolio_id, request_id)
            );
            CREATE INDEX IF NOT EXISTS exposure_reservations_active
                ON exposure_reservations(portfolio_id, state);
            CREATE TABLE IF NOT EXISTS broadcast_journal (
                idempotency_key TEXT PRIMARY KEY,
                payload_digest TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('IN_FLIGHT','BROADCAST','RECONCILIATION_REQUIRED','CONFIRMED','FAILED')),
                tx_hash TEXT,
                updated_at INTEGER NOT NULL DEFAULT (unixepoch())
            );
        """)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
            except BaseException:
                self._db.rollback()
                raise
            else:
                self._db.commit()

    def reserve_exposure(
        self,
        portfolio_id: str,
        request_id: str,
        size_bps: int,
        observed_exposure_bps: int,
        max_exposure_bps: int,
    ) -> bool:
        """Atomically reserve capacity; duplicate same-identity calls are idempotent."""
        if not isinstance(portfolio_id, str) or not portfolio_id.strip():
            raise ValueError("portfolio_id required")
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("request_id required")
        size = _integer(size_bps, "size_bps", minimum=1)
        observed = _integer(observed_exposure_bps, "observed_exposure_bps")
        cap = _integer(max_exposure_bps, "max_exposure_bps", minimum=1)
        if observed > cap or size > cap:
            raise PermissionError("EXPOSURE_LIMIT_REACHED")

        with self._transaction() as db:
            existing = db.execute(
                "SELECT size_bps, state FROM exposure_reservations WHERE portfolio_id=? AND request_id=?",
                (portfolio_id, request_id),
            ).fetchone()
            if existing is not None:
                if existing[0] != size:
                    raise ValueError("request identity reused with different exposure reservation")
                if existing[1] == "RELEASED":
                    raise PermissionError("reservation identity was already released")
                return True

            db.execute(
                "INSERT OR IGNORE INTO portfolio_baselines(portfolio_id, exposure_bps) VALUES (?,?)",
                (portfolio_id, observed),
            )
            baseline = db.execute(
                "SELECT exposure_bps FROM portfolio_baselines WHERE portfolio_id=?",
                (portfolio_id,),
            ).fetchone()[0]
            active = db.execute(
                "SELECT COALESCE(SUM(size_bps),0) FROM exposure_reservations "
                "WHERE portfolio_id=? AND state!='RELEASED'",
                (portfolio_id,),
            ).fetchone()[0]
            if baseline + active + size > cap:
                raise PermissionError("EXPOSURE_LIMIT_REACHED")
            db.execute(
                "INSERT INTO exposure_reservations(portfolio_id,request_id,size_bps,state) "
                "VALUES (?,?,?,'RESERVED')",
                (portfolio_id, request_id, size),
            )
        return True

    def mark_exposure_reconciliation_required(self, portfolio_id: str, request_id: str) -> None:
        with self._transaction() as db:
            result = db.execute(
                "UPDATE exposure_reservations SET state='RECONCILIATION_REQUIRED' "
                "WHERE portfolio_id=? AND request_id=? AND state='RESERVED'",
                (portfolio_id, request_id),
            )
            if result.rowcount != 1:
                row = db.execute(
                    "SELECT state FROM exposure_reservations WHERE portfolio_id=? AND request_id=?",
                    (portfolio_id, request_id),
                ).fetchone()
                if row is None or row[0] != "RECONCILIATION_REQUIRED":
                    raise ValueError("reservation is not active")

    def commit_exposure(self, portfolio_id: str, request_id: str) -> None:
        """Mark a confirmed trade committed; continue counting it until chain reconciliation."""
        with self._transaction() as db:
            result = db.execute(
                "UPDATE exposure_reservations SET state='COMMITTED' "
                "WHERE portfolio_id=? AND request_id=? AND state IN ('RESERVED','RECONCILIATION_REQUIRED')",
                (portfolio_id, request_id),
            )
            if result.rowcount != 1:
                row = db.execute(
                    "SELECT state FROM exposure_reservations WHERE portfolio_id=? AND request_id=?",
                    (portfolio_id, request_id),
                ).fetchone()
                if row is None or row[0] != "COMMITTED":
                    raise ValueError("reservation is not active")

    def release_exposure(self, portfolio_id: str, request_id: str, *, reconciled: bool = False) -> None:
        """Release a failed reservation; ambiguous/committed state needs reconciliation."""
        with self._transaction() as db:
            row = db.execute(
                "SELECT state FROM exposure_reservations WHERE portfolio_id=? AND request_id=?",
                (portfolio_id, request_id),
            ).fetchone()
            if row is None:
                raise ValueError("reservation not found")
            state = row[0]
            if state in ("RECONCILIATION_REQUIRED", "COMMITTED") and not reconciled:
                raise PermissionError("reconciliation required before release")
            if state == "RELEASED":
                return
            db.execute(
                "UPDATE exposure_reservations SET state='RELEASED' WHERE portfolio_id=? AND request_id=?",
                (portfolio_id, request_id),
            )

    def reconcile_portfolio_exposure(self, portfolio_id: str, observed_exposure_bps: int) -> None:
        """Apply a trusted chain/accounting snapshot and retire committed reservations."""
        if not isinstance(portfolio_id, str) or not portfolio_id.strip():
            raise ValueError("portfolio_id required")
        observed = _integer(observed_exposure_bps, "observed_exposure_bps")
        with self._transaction() as db:
            db.execute(
                "INSERT INTO portfolio_baselines(portfolio_id, exposure_bps) VALUES (?,?) "
                "ON CONFLICT(portfolio_id) DO UPDATE SET exposure_bps=excluded.exposure_bps",
                (portfolio_id, observed),
            )
            db.execute(
                "UPDATE exposure_reservations SET state='RELEASED' "
                "WHERE portfolio_id=? AND state='COMMITTED'",
                (portfolio_id,),
            )

    def claim_broadcast(self, idempotency_key: str, payload_digest: str) -> tuple[bool, str, str | None]:
        """Claim a first broadcast, or return journal state without resubmitting."""
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValueError("idempotency_key required")
        if not isinstance(payload_digest, str) or not payload_digest.strip():
            raise ValueError("payload_digest required")
        with self._transaction() as db:
            row = db.execute(
                "SELECT payload_digest,state,tx_hash FROM broadcast_journal WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if row is not None:
                if row[0] != payload_digest:
                    raise ValueError("broadcast identity reused with different payload digest")
                return False, row[1], row[2]
            db.execute(
                "INSERT INTO broadcast_journal(idempotency_key,payload_digest,state) VALUES (?,?,'IN_FLIGHT')",
                (idempotency_key, payload_digest),
            )
        return True, "IN_FLIGHT", None

    def record_broadcast(
        self,
        idempotency_key: str,
        payload_digest: str,
        state: str,
        tx_hash: str | None,
    ) -> None:
        if state not in _BROADCAST_STATES or state == "IN_FLIGHT":
            raise ValueError("invalid broadcast state")
        if tx_hash is not None and (not isinstance(tx_hash, str) or not tx_hash.strip()):
            raise ValueError("invalid transaction hash")
        with self._transaction() as db:
            row = db.execute(
                "SELECT payload_digest,state,tx_hash FROM broadcast_journal WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if row is None or row[0] != payload_digest:
                raise ValueError("broadcast claim missing or payload digest mismatch")
            old_state, old_hash = row[1], row[2]
            if old_hash is not None and tx_hash is not None and old_hash.lower() != tx_hash.lower():
                raise ValueError("broadcast transaction hash cannot change")
            allowed = {
                "IN_FLIGHT": {"BROADCAST", "RECONCILIATION_REQUIRED", "CONFIRMED", "FAILED"},
                "RECONCILIATION_REQUIRED": {"BROADCAST", "RECONCILIATION_REQUIRED", "CONFIRMED", "FAILED"},
                "BROADCAST": {"BROADCAST", "RECONCILIATION_REQUIRED", "CONFIRMED", "FAILED"},
                "CONFIRMED": {"CONFIRMED"},
                "FAILED": {"FAILED"},
            }
            if state not in allowed[old_state]:
                raise ValueError("invalid broadcast state transition")
            db.execute(
                "UPDATE broadcast_journal SET state=?,tx_hash=COALESCE(?,tx_hash),updated_at=unixepoch() "
                "WHERE idempotency_key=?",
                (state, tx_hash, idempotency_key),
            )

    def close(self) -> None:
        with self._lock:
            self._db.close()
