"""Persist immutable proposal/transaction pairs and fail closed on signing retries."""
from __future__ import annotations

import json
import os
import sqlite3

from .models import Direction, TradeProposal, TransactionEnvelope


class ProposalStore:
    def __init__(self, path: str = ":memory:") -> None:
        if path != ":memory:":
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(fd)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS proposals (
            request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
            proposal TEXT NOT NULL, transaction_json TEXT NOT NULL,
            signing_attempted INTEGER NOT NULL DEFAULT 0)""")
        self.db.commit()

    def get(self, request_id: str, fingerprint: str):
        row = self.db.execute(
            "SELECT fingerprint, proposal, transaction_json, signing_attempted FROM proposals WHERE request_id=?",
            (request_id,),
        ).fetchone()
        if row is None:
            return None
        if row[0] != fingerprint:
            raise ValueError("request identity reused with different intent or policy")
        p = json.loads(row[1])
        p["direction"] = Direction(p["direction"])
        t = json.loads(row[2])
        t["from_address"] = t.pop("from")
        t["to_address"] = t.pop("to")
        return TradeProposal(**p), TransactionEnvelope(**t), bool(row[3])

    def save(self, request_id: str, fingerprint: str, proposal, tx):
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO proposals(request_id,fingerprint,proposal,transaction_json) VALUES(?,?,?,?)",
                (request_id, fingerprint, proposal.canonical(), tx.canonical()),
            )
        return self.get(request_id, fingerprint)

    def claim_signing(self, request_id: str) -> bool:
        with self.db:
            result = self.db.execute(
                "UPDATE proposals SET signing_attempted=1 WHERE request_id=? AND signing_attempted=0",
                (request_id,),
            )
        return result.rowcount == 1

    def close(self) -> None:
        self.db.close()
