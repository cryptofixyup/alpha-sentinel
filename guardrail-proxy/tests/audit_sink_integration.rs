use alpha_sentinel_guardrail_proxy::audit::{
    AuditEvent, AuditSink, AuditSinkError, Decision, Outcome, PgAuditSink, ReasonCode, RuleId,
};
use chrono::Utc;
use sqlx::{postgres::PgPoolOptions, PgPool};
use std::time::Duration;
use uuid::Uuid;

async fn test_pool() -> Option<PgPool> {
    let url = match std::env::var("TEST_DATABASE_URL") {
        Ok(value) if !value.is_empty() => value,
        _ => {
            eprintln!("SKIP audit PostgreSQL integration test: TEST_DATABASE_URL is not set");
            return None;
        }
    };
    let pool = PgPoolOptions::new()
        .max_connections(1)
        .acquire_timeout(Duration::from_secs(2))
        .connect(&url)
        .await
        .expect("TEST_DATABASE_URL must point to a disposable PostgreSQL test database");
    sqlx::migrate!("./migrations")
        .run(&pool)
        .await
        .expect("audit migrations must apply to the disposable test database");
    Some(pool)
}

fn sample_event(payload_bytes: u64) -> AuditEvent {
    AuditEvent::new(
        Utc::now(),
        Decision::Reject,
        Some(RuleId::PromptOverride),
        Outcome::PolicyRejected,
        Some(ReasonCode::SignatureMatch),
        3,
        payload_bytes,
        env!("CARGO_PKG_VERSION"),
    )
    .unwrap()
}

#[tokio::test]
async fn postgres_append_is_idempotent_and_persists_metadata_only() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let sink = PgAuditSink::from_pool(pool.clone());
    let event = sample_event(23);
    let id = event.request_id();

    sink.append(&event, Duration::from_secs(1)).await.unwrap();
    sink.append(&event, Duration::from_secs(1)).await.unwrap();

    let count: i64 = sqlx::query_scalar("SELECT count(*) FROM audit.events WHERE request_id = $1")
        .bind(id)
        .fetch_one(&pool)
        .await
        .unwrap();
    assert_eq!(
        count, 1,
        "same ID and digest must not create duplicate rows"
    );

    let persisted: (String, String, i64) = sqlx::query_as(
        "SELECT decision, outcome, payload_bytes FROM audit.events WHERE request_id = $1",
    )
    .bind(id)
    .fetch_one(&pool)
    .await
    .unwrap();
    assert_eq!(
        persisted,
        ("reject".to_owned(), "policy_rejected".to_owned(), 23)
    );

    sqlx::query("DELETE FROM audit.events WHERE request_id = $1")
        .bind(id)
        .execute(&pool)
        .await
        .unwrap();
}

#[tokio::test]
async fn postgres_rejects_reuse_of_event_id_with_different_digest() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let sink = PgAuditSink::from_pool(pool.clone());
    let original = sample_event(23);
    let id = original.request_id();
    sink.append(&original, Duration::from_secs(1))
        .await
        .unwrap();

    // Exercise the SQL idempotency guard with a valid but different metadata digest.
    let accepted: bool = sqlx::query_scalar(
        "SELECT audit.append_event($1, '1', 'inspection_decision', $2, 'reject', 'SIG_PROMPT_OVERRIDE_001', 'policy_rejected', 'SIGNATURE_MATCH', 3, 24, $3, $4)",
    )
    .bind(id)
    .bind(Utc::now())
    .bind(env!("CARGO_PKG_VERSION"))
    .bind(vec![0xA5_u8; 32])
    .fetch_one(&pool)
    .await
    .unwrap();
    assert!(
        !accepted,
        "same ID with a different digest must fail closed"
    );

    sqlx::query("DELETE FROM audit.events WHERE request_id = $1")
        .bind(id)
        .execute(&pool)
        .await
        .unwrap();
}

#[tokio::test]
async fn pool_exhaustion_obeys_deadline() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let sink = PgAuditSink::from_pool(pool.clone());
    let held_connection = pool.acquire().await.unwrap();
    let event = sample_event(11);

    let result = sink.append(&event, Duration::from_millis(20)).await;
    assert_eq!(result.unwrap_err(), AuditSinkError::DeadlineExceeded);
    drop(held_connection);
}

#[tokio::test]
async fn runtime_role_can_execute_append_but_cannot_access_table_directly() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let role = format!("audit_runtime_test_{}", Uuid::new_v4().simple());
    sqlx::query(&format!("CREATE ROLE \"{role}\" NOLOGIN"))
        .execute(&pool)
        .await
        .expect("test database must permit creating disposable roles");
    sqlx::query(&format!("GRANT USAGE ON SCHEMA audit TO \"{role}\""))
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query(&format!(
        "GRANT EXECUTE ON FUNCTION audit.append_event(uuid, text, text, timestamptz, text, text, text, text, integer, bigint, text, bytea) TO \"{role}\""
    ))
    .execute(&pool)
    .await
    .unwrap();

    for privilege in ["SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"] {
        let allowed: bool =
            sqlx::query_scalar("SELECT has_table_privilege($1, 'audit.events', $2)")
                .bind(&role)
                .bind(privilege)
                .fetch_one(&pool)
                .await
                .unwrap();
        assert!(
            !allowed,
            "runtime role must not have direct {privilege} privilege"
        );
    }
    let can_execute: bool = sqlx::query_scalar(
        "SELECT has_function_privilege($1, 'audit.append_event(uuid,text,text,timestamptz,text,text,text,text,integer,bigint,text,bytea)', 'EXECUTE')",
    )
    .bind(&role)
    .fetch_one(&pool)
    .await
    .unwrap();
    assert!(can_execute, "runtime role needs EXECUTE on append function");

    // Remove the test role's grants before dropping the role; PostgreSQL
    // refuses DROP ROLE while schema/function privileges still reference it.
    sqlx::query(&format!("DROP OWNED BY \\"{role}\\""))
        .execute(&pool)
        .await
        .expect("test role grants must be removable");
    sqlx::query(&format!("DROP ROLE \\"{role}\\""))
        .execute(&pool)
        .await
        .expect("disposable test role must be removable");
}

#[tokio::test]
async fn closed_pool_fails_closed_without_exposing_database_errors() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let sink = PgAuditSink::from_pool(pool.clone());
    let event = sample_event(11);
    pool.close().await;

    assert_eq!(
        sink.append(&event, Duration::from_millis(250))
            .await
            .unwrap_err(),
        AuditSinkError::Unavailable
    );
}
