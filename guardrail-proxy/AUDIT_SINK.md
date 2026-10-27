# PostgreSQL audit sink implementation

This branch adds an initial PostgreSQL-backed, metadata-only audit persistence layer. It is a separate implementation branch; PR #62 remains unchanged and inspection-only.

## Components

- `migrations/20261027000100_audit_events.sql`: constrained `audit.events` table and an idempotent append function.
- `src/audit.rs`: typed allowlisted event builder, bounded concurrent writer, PostgreSQL adapter, event digest for idempotency checks, and fixed error classifications.
- `tests/audit_sink_integration.rs`: PostgreSQL integration/fault tests for idempotent append, conflicting event IDs, pool exhaustion, closed-sink failure, and runtime-role privileges.
- `.github/workflows/audit-sink.yml`: unit/build checks and PostgreSQL-backed integration tests.

The event digest covers only the serialized metadata event. It is **not** a prompt/body hash, a cryptographic checkpoint, or proof against a privileged database administrator. Independent signed checkpoints remain a separate implementation gate.

## Runtime role model

Apply migrations with a dedicated migration/owner role, not the application identity. The function owner should be a dedicated `NOLOGIN` role with only the privileges needed to append. The runtime identity should not own the schema/table and should not be a member of the owner role.

After migrations, grant only schema usage and function execution to the runtime identity. Example (replace role/database names for the deployment):

```sql
GRANT USAGE ON SCHEMA audit TO audit_runtime;
GRANT EXECUTE ON FUNCTION audit.append_event(
  uuid, text, text, timestamptz, text, text, text, text,
  integer, bigint, text, bytea
) TO audit_runtime;
```

Do not grant direct SELECT, INSERT, UPDATE, DELETE, or TRUNCATE on `audit.events` to the runtime role. Revoke any inherited grants and verify effective privileges, not just direct grants. Because the append function is `SECURITY DEFINER`, its owner and deployment grants are security-critical. Review the migration owner and function definition before deployment.

## Failure semantics

- The adapter uses a 32-write semaphore and rejects additional concurrent writes immediately rather than maintaining an unbounded application queue.
- The pool is capped at 32 connections with a 250 ms acquisition timeout.
- Each append has a caller-provided deadline. A timeout is an uncertain commit outcome, not proof that the event was absent.
- Retrying the same event ID and metadata digest is idempotent. Reusing an ID with different metadata fails closed.
- Sink failures are mapped to fixed error variants; raw SQL errors are not returned to the caller.
- Callers must return no success for a mandatory-audit request until append acknowledgement succeeds. This module is not yet wired into the HTTP inspection route, so the current prototype endpoint does not gain this guarantee merely by including the module.

## Test execution

Unit/build checks:

```sh
cargo fmt --all -- --check
cargo test
cargo build --release
```

PostgreSQL fault-injection suite, using a **disposable test database** whose test identity can create and drop roles:

```sh
TEST_DATABASE_URL='postgres://audit_test:...@localhost:5432/audit_test' \
  cargo test --test audit_sink_integration -- --test-threads=1
```

The integration tests apply the SQLx migration to the configured database and create/delete synthetic test rows and a temporary role. Never point `TEST_DATABASE_URL` at production or a database containing real audit data. If the variable is unset, the integration tests report a skip and do not provide database-backed evidence.

## Not yet established

This branch is an implementation candidate, not production approval. CI must execute successfully before claiming tests pass. Deployment-specific PostgreSQL durability settings, managed-storage guarantees, least-privilege role setup, retention/backup behavior, and independent cryptographic checkpoints still require verification. No claim is made that the sink survives permanent host/storage loss or prevents a privileged DBA from rewriting uncheckpointed records.
