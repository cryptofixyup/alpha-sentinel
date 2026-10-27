use async_trait::async_trait;
use chrono::{DateTime, Utc};
use serde::Serialize;
use sha2::{Digest, Sha256};
use sqlx::{postgres::PgPoolOptions, PgPool};
use std::{sync::Arc, time::Duration};
use tokio::sync::Semaphore;
use uuid::Uuid;

pub const MAX_EVENT_BYTES: usize = 16 * 1024;
pub const MAX_PAYLOAD_BYTES: u64 = 64 * 1024 * 1024;
pub const MAX_DURATION_MS: u32 = 300_000;
pub const MAX_CONCURRENT_WRITES: usize = 32;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Decision {
    Allow,
    Reject,
    Error,
}

impl Decision {
    fn as_db(self) -> &'static str {
        match self {
            Self::Allow => "allow",
            Self::Reject => "reject",
            Self::Error => "error",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Outcome {
    InspectionAllowed,
    PolicyRejected,
    InvalidRequest,
    RequestTooLarge,
    TimedOut,
    InternalError,
}

impl Outcome {
    fn as_db(self) -> &'static str {
        match self {
            Self::InspectionAllowed => "inspection_allowed",
            Self::PolicyRejected => "policy_rejected",
            Self::InvalidRequest => "invalid_request",
            Self::RequestTooLarge => "request_too_large",
            Self::TimedOut => "timed_out",
            Self::InternalError => "internal_error",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum RuleId {
    #[serde(rename = "SIG_PROMPT_OVERRIDE_001")]
    PromptOverride,
    #[serde(rename = "SIG_SYSTEM_PROMPT_001")]
    SystemPrompt,
    #[serde(rename = "SIG_ENV_EXFILTRATION_001")]
    EnvironmentExfiltration,
    #[serde(rename = "SIG_SQL_DROP_001")]
    SqlDrop,
}

impl RuleId {
    fn as_db(self) -> &'static str {
        match self {
            Self::PromptOverride => "SIG_PROMPT_OVERRIDE_001",
            Self::SystemPrompt => "SIG_SYSTEM_PROMPT_001",
            Self::EnvironmentExfiltration => "SIG_ENV_EXFILTRATION_001",
            Self::SqlDrop => "SIG_SQL_DROP_001",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum ReasonCode {
    #[serde(rename = "SIGNATURE_MATCH")]
    SignatureMatch,
    #[serde(rename = "MALFORMED_REQUEST")]
    MalformedRequest,
    #[serde(rename = "BODY_LIMIT_EXCEEDED")]
    BodyLimitExceeded,
    #[serde(rename = "DEADLINE_EXCEEDED")]
    DeadlineExceeded,
    #[serde(rename = "INSPECTION_FAILURE")]
    InspectionFailure,
}

impl ReasonCode {
    fn as_db(self) -> &'static str {
        match self {
            Self::SignatureMatch => "SIGNATURE_MATCH",
            Self::MalformedRequest => "MALFORMED_REQUEST",
            Self::BodyLimitExceeded => "BODY_LIMIT_EXCEEDED",
            Self::DeadlineExceeded => "DEADLINE_EXCEEDED",
            Self::InspectionFailure => "INSPECTION_FAILURE",
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct AuditEvent {
    schema_version: &'static str,
    event_type: &'static str,
    request_id: Uuid,
    timestamp: DateTime<Utc>,
    decision: Decision,
    rule_id: Option<RuleId>,
    outcome: Outcome,
    reason_code: Option<ReasonCode>,
    duration_ms: u32,
    payload_bytes: u64,
    service_version: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EventBuildError {
    InvalidDecisionOutcome,
    InvalidRuleCombination,
    DurationOutOfRange,
    PayloadSizeOutOfRange,
    InvalidServiceVersion,
    EventTooLarge,
}

impl AuditEvent {
    /// Build an allowlisted metadata-only event. No request body, headers,
    /// caller-controlled ID, error string, or content fingerprint is accepted.
    pub fn new(
        request_id: Uuid,
        timestamp: DateTime<Utc>,
        decision: Decision,
        rule_id: Option<RuleId>,
        outcome: Outcome,
        reason_code: Option<ReasonCode>,
        duration_ms: u32,
        payload_bytes: u64,
        service_version: &str,
    ) -> Result<Self, EventBuildError> {
        if duration_ms > MAX_DURATION_MS {
            return Err(EventBuildError::DurationOutOfRange);
        }
        if payload_bytes > MAX_PAYLOAD_BYTES {
            return Err(EventBuildError::PayloadSizeOutOfRange);
        }
        if service_version.is_empty()
            || service_version.len() > 64
            || !service_version
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'+' | b'-'))
        {
            return Err(EventBuildError::InvalidServiceVersion);
        }

        let consistent = matches!(
            (decision, outcome),
            (Decision::Allow, Outcome::InspectionAllowed)
                | (Decision::Reject, Outcome::PolicyRejected)
                | (Decision::Reject, Outcome::InvalidRequest)
                | (Decision::Reject, Outcome::RequestTooLarge)
                | (Decision::Error, Outcome::TimedOut)
                | (Decision::Error, Outcome::InternalError)
        );
        if !consistent {
            return Err(EventBuildError::InvalidDecisionOutcome);
        }

        match (outcome, rule_id, reason_code) {
            (Outcome::InspectionAllowed, None, None) => {}
            (Outcome::PolicyRejected, Some(_), Some(ReasonCode::SignatureMatch)) => {}
            (Outcome::InvalidRequest, None, Some(ReasonCode::MalformedRequest)) => {}
            (Outcome::RequestTooLarge, None, Some(ReasonCode::BodyLimitExceeded)) => {}
            (Outcome::TimedOut, None, Some(ReasonCode::DeadlineExceeded)) => {}
            (Outcome::InternalError, None, Some(ReasonCode::InspectionFailure)) => {}
            _ => return Err(EventBuildError::InvalidRuleCombination),
        }

        let event = Self {
            schema_version: "1",
            event_type: "inspection_decision",
            request_id,
            timestamp,
            decision,
            rule_id,
            outcome,
            reason_code,
            duration_ms,
            payload_bytes,
            service_version: service_version.to_owned(),
        };
        if serde_json::to_vec(&event)
            .map_err(|_| EventBuildError::EventTooLarge)?
            .len()
            > MAX_EVENT_BYTES
        {
            return Err(EventBuildError::EventTooLarge);
        }
        Ok(event)
    }

    pub fn request_id(&self) -> Uuid {
        self.request_id
    }

    fn digest(&self) -> Result<Vec<u8>, AuditSinkError> {
        // Digest covers only the allowlisted metadata event, never request content.
        let bytes = serde_json::to_vec(self).map_err(|_| AuditSinkError::InvalidEvent)?;
        let digest = Sha256::digest(bytes);
        Ok(digest.to_vec())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AuditSinkError {
    Unavailable,
    DeadlineExceeded,
    IdempotencyConflict,
    InvalidEvent,
    Saturated,
}

#[async_trait]
pub trait AuditSink: Send + Sync {
    async fn append(&self, event: &AuditEvent, deadline: Duration) -> Result<(), AuditSinkError>;
}

#[derive(Clone)]
pub struct PgAuditSink {
    pool: PgPool,
    write_slots: Arc<Semaphore>,
}

impl PgAuditSink {
    pub async fn connect(database_url: &str) -> Result<Self, AuditSinkError> {
        let pool = PgPoolOptions::new()
            .max_connections(32)
            .acquire_timeout(Duration::from_millis(250))
            .connect(database_url)
            .await
            .map_err(|_| AuditSinkError::Unavailable)?;
        Ok(Self {
            pool,
            write_slots: Arc::new(Semaphore::new(MAX_CONCURRENT_WRITES)),
        })
    }

    pub fn from_pool(pool: PgPool) -> Self {
        Self {
            pool,
            write_slots: Arc::new(Semaphore::new(MAX_CONCURRENT_WRITES)),
        }
    }

    pub fn pool(&self) -> &PgPool {
        &self.pool
    }
}

#[async_trait]
impl AuditSink for PgAuditSink {
    async fn append(&self, event: &AuditEvent, deadline: Duration) -> Result<(), AuditSinkError> {
        // Reject overload immediately instead of accumulating unbounded waiters.
        let _permit = Arc::clone(&self.write_slots)
            .try_acquire_owned()
            .map_err(|_| AuditSinkError::Saturated)?;
        let digest = event.digest()?;
        let append = sqlx::query_scalar::<_, bool>(
            "SELECT audit.append_event($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)",
        )
        .bind(event.request_id)
        .bind(event.schema_version)
        .bind(event.event_type)
        .bind(event.timestamp)
        .bind(event.decision.as_db())
        .bind(event.rule_id.map(RuleId::as_db))
        .bind(event.outcome.as_db())
        .bind(event.reason_code.map(ReasonCode::as_db))
        .bind(i32::try_from(event.duration_ms).map_err(|_| AuditSinkError::InvalidEvent)?)
        .bind(i64::try_from(event.payload_bytes).map_err(|_| AuditSinkError::InvalidEvent)?)
        .bind(&event.service_version)
        .bind(digest)
        .fetch_one(&self.pool);

        match tokio::time::timeout(deadline, append).await {
            Err(_) => Err(AuditSinkError::DeadlineExceeded),
            Ok(Err(_)) => Err(AuditSinkError::Unavailable),
            Ok(Ok(true)) => Ok(()),
            Ok(Ok(false)) => Err(AuditSinkError::IdempotencyConflict),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn event() -> AuditEvent {
        AuditEvent::new(
            Uuid::new_v4(),
            Utc::now(),
            Decision::Reject,
            Some(RuleId::PromptOverride),
            Outcome::PolicyRejected,
            Some(ReasonCode::SignatureMatch),
            2,
            42,
            env!("CARGO_PKG_VERSION"),
        )
        .unwrap()
    }

    #[test]
    fn serializes_only_allowlisted_metadata() {
        let event = event();
        let encoded = serde_json::to_string(&event).unwrap();
        assert!(encoded.contains("SIG_PROMPT_OVERRIDE_001"));
        assert!(!encoded.contains("prompt"));
        assert!(!encoded.contains("secret"));
        assert!(encoded.len() <= MAX_EVENT_BYTES);
    }

    #[test]
    fn rejects_decision_outcome_mismatch() {
        let result = AuditEvent::new(
            Uuid::new_v4(),
            Utc::now(),
            Decision::Allow,
            None,
            Outcome::PolicyRejected,
            Some(ReasonCode::SignatureMatch),
            1,
            1,
            env!("CARGO_PKG_VERSION"),
        );
        assert_eq!(result.unwrap_err(), EventBuildError::InvalidDecisionOutcome);
    }

    #[test]
    fn rejects_unbounded_fields() {
        assert_eq!(
            AuditEvent::new(
                Uuid::new_v4(),
                Utc::now(),
                Decision::Allow,
                None,
                Outcome::InspectionAllowed,
                None,
                MAX_DURATION_MS + 1,
                0,
                env!("CARGO_PKG_VERSION"),
            )
            .unwrap_err(),
            EventBuildError::DurationOutOfRange
        );
        assert_eq!(
            AuditEvent::new(
                Uuid::new_v4(),
                Utc::now(),
                Decision::Allow,
                None,
                Outcome::InspectionAllowed,
                None,
                0,
                MAX_PAYLOAD_BYTES + 1,
                env!("CARGO_PKG_VERSION"),
            )
            .unwrap_err(),
            EventBuildError::PayloadSizeOutOfRange
        );
    }

    #[tokio::test]
    async fn saturated_sink_rejects_without_waiting_for_database() {
        let pool = PgPoolOptions::new()
            .max_connections(1)
            .connect_lazy("postgres://invalid:invalid@127.0.0.1:1/unused")
            .unwrap();
        let sink = PgAuditSink::from_pool(pool);
        let mut permits = Vec::new();
        for _ in 0..MAX_CONCURRENT_WRITES {
            permits.push(Arc::clone(&sink.write_slots).acquire_owned().await.unwrap());
        }
        let event = event();
        assert_eq!(
            sink.append(&event, Duration::from_secs(1))
                .await
                .unwrap_err(),
            AuditSinkError::Saturated
        );
        drop(permits);
    }

    #[test]
    fn rejects_free_form_service_version() {
        assert_eq!(
            AuditEvent::new(
                Uuid::new_v4(),
                Utc::now(),
                Decision::Allow,
                None,
                Outcome::InspectionAllowed,
                None,
                0,
                0,
                "/tmp/secret",
            )
            .unwrap_err(),
            EventBuildError::InvalidServiceVersion
        );
    }
}
