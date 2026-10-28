import pytest

from security_boundary.execution_state import SQLiteExecutionState


def test_reservations_are_atomic_and_prevent_concurrent_overexposure(tmp_path):
    db = str(tmp_path / "execution-state.sqlite3")
    first = SQLiteExecutionState(db)
    second = SQLiteExecutionState(db)
    try:
        assert first.reserve_exposure("wallet:1", "trade-a", 1200, 1000, 5000)
        assert second.reserve_exposure("wallet:1", "trade-b", 2500, 1000, 5000)
        with pytest.raises(PermissionError, match="EXPOSURE_LIMIT_REACHED"):
            first.reserve_exposure("wallet:1", "trade-c", 1400, 1000, 5000)
    finally:
        first.close()
        second.close()


def test_reservation_idempotency_and_identity_binding(tmp_path):
    state = SQLiteExecutionState(str(tmp_path / "state.sqlite3"))
    try:
        assert state.reserve_exposure("p", "same-key", 500, 100, 1000)
        assert state.reserve_exposure("p", "same-key", 500, 100, 1000)
        with pytest.raises(ValueError, match="identity reused"):
            state.reserve_exposure("p", "same-key", 600, 100, 1000)
    finally:
        state.close()


def test_release_requires_explicit_reconciliation_for_ambiguous_reservation(tmp_path):
    state = SQLiteExecutionState(str(tmp_path / "state.sqlite3"))
    try:
        state.reserve_exposure("p", "trade", 400, 100, 1000)
        state.mark_exposure_reconciliation_required("p", "trade")
        with pytest.raises(PermissionError, match="reconciliation"):
            state.release_exposure("p", "trade")
        state.release_exposure("p", "trade", reconciled=True)
        assert state.reserve_exposure("p", "next", 800, 100, 1000)
    finally:
        state.close()


def test_committed_reservations_remain_counted_until_chain_snapshot_reconciles(tmp_path):
    state = SQLiteExecutionState(str(tmp_path / "state.sqlite3"))
    try:
        state.reserve_exposure("p", "trade", 400, 100, 1000)
        state.commit_exposure("p", "trade")
        with pytest.raises(PermissionError, match="EXPOSURE_LIMIT_REACHED"):
            state.reserve_exposure("p", "next", 600, 100, 1000)
        state.reconcile_portfolio_exposure("p", 500)
        assert state.reserve_exposure("p", "next", 400, 500, 1000)
    finally:
        state.close()


def test_broadcast_claim_is_durable_and_never_claimed_twice(tmp_path):
    db = str(tmp_path / "state.sqlite3")
    first = SQLiteExecutionState(db)
    second = SQLiteExecutionState(db)
    try:
        assert first.claim_broadcast("key", "digest") == (True, "IN_FLIGHT", None)
        assert second.claim_broadcast("key", "digest") == (False, "IN_FLIGHT", None)
        with pytest.raises(ValueError, match="identity reused"):
            second.claim_broadcast("key", "different-digest")
    finally:
        first.close()
        second.close()


def test_broadcast_journal_resumes_by_hash_without_resubmission(tmp_path):
    db = str(tmp_path / "state.sqlite3")
    first = SQLiteExecutionState(db)
    assert first.claim_broadcast("key", "digest") == (True, "IN_FLIGHT", None)
    first.close()
    resumed = SQLiteExecutionState(db)
    try:
        assert resumed.claim_broadcast("key", "digest") == (False, "IN_FLIGHT", None)
        resumed.record_broadcast("key", "digest", "BROADCAST", "0x" + "a" * 64)
        assert resumed.claim_broadcast("key", "digest") == (
            False, "BROADCAST", "0x" + "a" * 64
        )
    finally:
        resumed.close()


def test_broadcast_state_transitions_are_restricted(tmp_path):
    state = SQLiteExecutionState(str(tmp_path / "state.sqlite3"))
    try:
        state.claim_broadcast("key", "digest")
        with pytest.raises(ValueError, match="invalid broadcast state"):
            state.record_broadcast("key", "digest", "MAGIC_SUCCESS", None)
        state.record_broadcast("key", "digest", "RECONCILIATION_REQUIRED", None)
        assert state.claim_broadcast("key", "digest") == (
            False, "RECONCILIATION_REQUIRED", None
        )
    finally:
        state.close()


def test_concurrent_reservations_cannot_both_consume_same_capacity(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    db = str(tmp_path / "concurrent.sqlite3")
    states = [SQLiteExecutionState(db), SQLiteExecutionState(db)]

    def reserve(pair):
        state, request_id = pair
        try:
            state.reserve_exposure("portfolio", request_id, 3000, 1000, 5000)
            return "reserved"
        except PermissionError:
            return "blocked"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(reserve, zip(states, ("a", "b"))))
        assert sorted(outcomes) == ["blocked", "reserved"]
    finally:
        for state in states:
            state.close()


def test_production_rejects_in_memory_execution_state(monkeypatch):
    monkeypatch.setenv("ALPHA_SENTINEL_ENV", "production")
    with pytest.raises(RuntimeError, match="persistent shared execution-state storage"):
        SQLiteExecutionState(":memory:")
