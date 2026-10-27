# Audit pre-handler and migration safety remediation

Status: draft implementation candidate. This document does not certify a deployment database or approve production promotion.

## Pre-handler request rejection coverage

The /v1/agent/invoke route installs audit middleware before Axum's JSON extractor. The middleware:

- bounds body buffering at MAX_PAYLOAD_BYTES and rejects an oversized declared Content-Length before buffering;
- audits oversized-body rejections as request_too_large / BODY_LIMIT_EXCEEDED;
- audits unsupported/missing JSON content types and JSON deserialization failures as invalid_request / MALFORMED_REQUEST;
- returns the HTTP rejection only after the audit append is acknowledged; if append acknowledgement fails, it returns the generic fail-closed 503;
- passes valid JSON onward to the existing handler, which records the inspection decision as before.

For an oversized body whose actual length cannot safely be established, payload_bytes is capped at the configured maximum. It must not be interpreted as an exact byte count. /health remains an intentionally unaudited liveness endpoint; this does not claim to record requests rejected by infrastructure before the application process (for example, a reverse proxy or load balancer).

## SQLx migration immutability

Never edit a migration that has been applied to a persistent environment. Before changing migration history, inspect the exact migration version and checksum in that environment's _sqlx_migrations table and compare them with the repository artifact. Do not infer deployment history from CI.

- If 20261027000100_audit_events.sql has not been applied anywhere persistent, changes can be made before its first release, but should still be reviewed as a single immutable release artifact.
- If it has been applied, restore the original migration bytes and create a new, later versioned migration for any schema/function changes.
- If environments disagree, stop rollout and reconcile the migration ledger before applying further migrations. Do not delete or rewrite migration-ledger rows to bypass checksum validation.
- Record the migration file checksum, database identity/environment, query result, and review timestamp as release evidence. Redact connection strings and secrets.

The repository-only workflow cannot prove whether a production or customer database has applied this migration. That requires read-only inspection of each relevant database's migration ledger.

## Acceptance tests

Required CI evidence for this branch:

1. malformed JSON returns 400 only after one audit append;
2. unsupported content type returns 415 only after one audit append;
3. declared oversized body returns 413 only after one audit append;
4. an audit append failure causes a fail-closed 503 for each pre-handler rejection class;
5. valid requests still reach the existing decision handler, which waits for audit acknowledgement.

These tests cover application middleware behavior, not upstream proxy rejection or deployment database history/privileges.
