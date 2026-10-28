use alpha_sentinel_guardrail_proxy::audit::{
    AuditEvent, AuditSink, AuditSinkError, Decision, Outcome, PgAuditSink, ReasonCode, RuleId,
};
use chrono::Utc;
use sqlx::{postgres::PgPoolOptions, Executor, PgPool};
use std::time::Duration;
use uuid::Uuid;

async fn test_pool() -> Option<PgPool> {
    let url = match std::env::var("TEST_DATABASE_URL") {
        Ok(value) if !value.trim().is_empty() => value,
        _ if std::env::var_os("CI").is_some() => panic!("TEST_DATABASE_URL must be set to a non-empty PostgreSQL URL in CI"),
        _ => {
            eprintln!("SKIP: PostgreSQL audit integration test requires TEST_DATABASE_URL outside CI");
            return None;
        }
    };
    eprintln!("RUN: PostgreSQL-backed audit integration test (database URL configured)");
    let pool = PgPoolOptions::new().max_connections(2).acquire_timeout(Duration::from_secs(2)).connect(&url).await
        .expect("TEST_DATABASE_URL must point to a disposable PostgreSQL test database");
    sqlx::migrate!("./migrations").run(&pool).await
        .expect("audit migrations must apply to the disposable test database");
    Some(pool)
}

fn sample_event(payload_bytes: u64) -> AuditEvent {
    AuditEvent::new(Utc::now(), Decision::Reject, Some(RuleId::PromptOverride),
        Outcome::PolicyRejected, Some(ReasonCode::SignatureMatch), 3, payload_bytes,
        env!("CARGO_PKG_VERSION")).unwrap()
}

#[tokio::test]
async fn postgres_append_is_idempotent_and_persists_metadata_only() {
    let Some(pool) = test_pool().await else { return; };
    let sink = PgAuditSink::from_pool(pool.clone());
    let event = sample_event(23);
    let id = event.request_id();
    sink.append(&event, Duration::from_secs(1)).await.unwrap();
    sink.append(&event, Duration::from_secs(1)).await.unwrap();
    let count: i64 = sqlx::query_scalar("SELECT count(*) FROM audit.events WHERE request_id = $1")
        .bind(id).fetch_one(&pool).await.unwrap();
    assert_eq!(count, 1, "same ID and digest must not create duplicate rows");
    let persisted: (String, String, i64) = sqlx::query_as(
        "SELECT decision, outcome, payload_bytes FROM audit.events WHERE request_id = $1")
        .bind(id).fetch_one(&pool).await.unwrap();
    assert_eq!(persisted, ("reject".into(), "policy_rejected".into(), 23));
    sqlx::query("DELETE FROM audit.events WHERE request_id = $1").bind(id).execute(&pool).await.unwrap();
}

#[tokio::test]
async fn postgres_rejects_reuse_of_event_id_with_different_digest() {
    let Some(pool) = test_pool().await else { return; };
    let sink = PgAuditSink::from_pool(pool.clone());
    let original = sample_event(23);
    let id = original.request_id();
    sink.append(&original, Duration::from_secs(1)).await.unwrap();
    let accepted: bool = sqlx::query_scalar(
        "SELECT audit.append_event($1, '1', 'inspection_decision', $2, 'reject', 'SIG_PROMPT_OVERRIDE_001', 'policy_rejected', 'SIGNATURE_MATCH', 3, 24, $3, $4)")
        .bind(id).bind(Utc::now()).bind(env!("CARGO_PKG_VERSION")).bind(vec![0xA5_u8; 32])
        .fetch_one(&pool).await.unwrap();
    assert!(!accepted, "same ID with a different digest must fail closed");
    sqlx::query("DELETE FROM audit.events WHERE request_id = $1").bind(id).execute(&pool).await.unwrap();
}

#[tokio::test]
async fn pool_exhaustion_obeys_deadline() {
    let Some(pool) = test_pool().await else { return; };
    let sink = PgAuditSink::from_pool(pool.clone());
    let held_connection = pool.acquire().await.unwrap();
    let event = sample_event(11);
    assert_eq!(sink.append(&event, Duration::from_millis(20)).await.unwrap_err(), AuditSinkError::DeadlineExceeded);
    drop(held_connection);
}

#[tokio::test]
async fn function_owner_isolated_and_runtime_role_is_append_only() {
    let Some(pool) = test_pool().await else { return; };

    let owner: (String, bool, bool, bool) = sqlx::query_as(
        "SELECT r.rolname, r.rolcanlogin, r.rolsuper, r.rolbypassrls FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_roles r ON r.oid=p.proowner WHERE p.oid='audit.append_event(uuid,text,text,timestamptz,text,text,text,text,integer,bigint,text,bytea)'::regprocedure")
        .fetch_one(&pool).await.unwrap();
    assert_eq!(owner.0, "audit_function_owner", "SECURITY DEFINER owner must be dedicated");
    assert!(!owner.1 && !owner.2 && !owner.3, "function owner must be NOLOGIN, non-superuser, and not bypass RLS");

    let role = format!("audit_runtime_test_{}", Uuid::new_v4().simple());
    sqlx::query(&format!("CREATE ROLE \"{role}\" NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"))
        .execute(&pool).await.expect("disposable test database must permit creating roles");
    let setup = async {
        sqlx::query(&format!("GRANT USAGE ON SCHEMA audit TO \"{role}\"")).execute(&pool).await?;
        sqlx::query(&format!("GRANT EXECUTE ON FUNCTION audit.append_event(uuid,text,text,timestamptz,text,text,text,text,integer,bigint,text,bytea) TO \"{role}\"")).execute(&pool).await?;
        Ok::<(), sqlx::Error>(())
    }.await;
    if let Err(error) = setup {
        let _ = sqlx::query(&format!("DROP ROLE \"{role}\"")).execute(&pool).await;
        panic!("could not configure disposable runtime role: {error}");
    }

    for privilege in ["SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"] {
        let allowed: bool = sqlx::query_scalar("SELECT has_table_privilege($1, 'audit.events', $2)")
            .bind(&role).bind(privilege).fetch_one(&pool).await.unwrap();
        assert!(!allowed, "runtime role must not have direct or inherited {privilege} privilege");
    }
    let can_execute: bool = sqlx::query_scalar(
        "SELECT has_function_privilege($1, 'audit.append_event(uuid,text,text,timestamptz,text,text,text,text,integer,bigint,text,bytea)', 'EXECUTE')")
        .bind(&role).fetch_one(&pool).await.unwrap();
    assert!(can_execute, "runtime role needs EXECUTE on append function");

    let inherits_owner: bool = sqlx::query_scalar("SELECT pg_has_role($1, 'audit_function_owner', 'MEMBER')")
        .bind(&role).fetch_one(&pool).await.unwrap();
    assert!(!inherits_owner, "runtime identity must not be a member of the function-owner role");

    let event = sample_event(19);
    let id = event.request_id();
    {
        let mut connection = pool.acquire().await.unwrap();
        sqlx::query(&format!("SET ROLE \"{role}\"")).execute(&mut *connection).await.unwrap();
        for statement in [
            "SELECT * FROM audit.events LIMIT 1",
            "INSERT INTO audit.events (request_id,schema_version,event_type,observed_at,decision,outcome,reason_code,duration_ms,payload_bytes,service_version,event_digest) VALUES (gen_random_uuid(),'1','inspection_decision',now(),'allow','inspection_allowed',NULL,1,1,'test',decode(repeat('00',32),'hex'))",
            "UPDATE audit.events SET service_version='tampered'",
            "DELETE FROM audit.events",
            "TRUNCATE audit.events",
        ] {
            assert!(connection.execute(statement).await.is_err(), "direct operation unexpectedly succeeded: {statement}");
        }
        let appended: bool = sqlx::query_scalar(
            "SELECT audit.append_event($1,'1','inspection_decision',$2,'reject','SIG_PROMPT_OVERRIDE_001','policy_rejected','SIGNATURE_MATCH',3,19,$3,$4)")
            .bind(id).bind(Utc::now()).bind(env!("CARGO_PKG_VERSION")).bind(vec![0x19_u8;32])
            .fetch_one(&mut *connection).await.expect("runtime role must append via SECURITY DEFINER");
        assert!(appended, "first append should report inserted");
        sqlx::query("RESET ROLE").execute(&mut *connection).await.unwrap();
    }
    let persisted: i64 = sqlx::query_scalar("SELECT count(*) FROM audit.events WHERE request_id=$1")
        .bind(id).fetch_one(&pool).await.unwrap();
    assert_eq!(persisted, 1, "successful function append must persist one event");
    sqlx::query("DELETE FROM audit.events WHERE request_id=$1").bind(id).execute(&pool).await.unwrap();

    sqlx::query(&format!("DROP OWNED BY \"{role}\"")).execute(&pool).await.unwrap();
    sqlx::query(&format!("DROP ROLE \"{role}\"")).execute(&pool).await.unwrap();
}

#[tokio::test]
async fn closed_pool_fails_closed_without_exposing_database_errors() {
    let Some(pool) = test_pool().await else { return; };
    let sink = PgAuditSink::from_pool(pool.clone());
    let event = sample_event(11);
    pool.close().await;
    assert_eq!(sink.append(&event, Duration::from_millis(250)).await.unwrap_err(), AuditSinkError::Unavailable);
}
