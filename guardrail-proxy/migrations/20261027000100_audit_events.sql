-- Migration: metadata-only audit event persistence.
-- Apply as a dedicated migration owner. Runtime identity should receive EXECUTE
-- on audit.append_event only, not direct table read/write privileges.
CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE IF NOT EXISTS audit.events (
    request_id uuid PRIMARY KEY,
    schema_version text NOT NULL CHECK (schema_version = '1'),
    event_type text NOT NULL CHECK (event_type = 'inspection_decision'),
    observed_at timestamptz NOT NULL,
    decision text NOT NULL CHECK (decision IN ('allow', 'reject', 'error')),
    rule_id text NULL CHECK (
        rule_id IS NULL OR rule_id IN (
            'SIG_PROMPT_OVERRIDE_001',
            'SIG_SYSTEM_PROMPT_001',
            'SIG_ENV_EXFILTRATION_001',
            'SIG_SQL_DROP_001'
        )
    ),
    outcome text NOT NULL CHECK (outcome IN (
        'inspection_allowed',
        'policy_rejected',
        'invalid_request',
        'request_too_large',
        'timed_out',
        'internal_error'
    )),
    reason_code text NULL CHECK (reason_code IS NULL OR reason_code IN (
        'SIGNATURE_MATCH',
        'MALFORMED_REQUEST',
        'BODY_LIMIT_EXCEEDED',
        'DEADLINE_EXCEEDED',
        'INSPECTION_FAILURE'
    )),
    duration_ms integer NOT NULL CHECK (duration_ms BETWEEN 0 AND 300000),
    payload_bytes bigint NOT NULL CHECK (payload_bytes BETWEEN 0 AND 67108864),
    service_version varchar(64) NOT NULL CHECK (service_version ~ '^[A-Za-z0-9._+-]{1,64}$'),
    event_digest bytea NOT NULL CHECK (octet_length(event_digest) = 32),
    ingested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (
        (decision = 'allow' AND outcome = 'inspection_allowed' AND rule_id IS NULL)
        OR
        (decision = 'reject' AND outcome IN ('policy_rejected', 'invalid_request', 'request_too_large'))
        OR
        (decision = 'error' AND outcome IN ('timed_out', 'internal_error'))
    ),
    CHECK (
        (outcome = 'inspection_allowed' AND reason_code IS NULL AND rule_id IS NULL)
        OR (outcome = 'policy_rejected' AND reason_code = 'SIGNATURE_MATCH' AND rule_id IS NOT NULL)
        OR (outcome = 'invalid_request' AND reason_code = 'MALFORMED_REQUEST' AND rule_id IS NULL)
        OR (outcome = 'request_too_large' AND reason_code = 'BODY_LIMIT_EXCEEDED' AND rule_id IS NULL)
        OR (outcome = 'timed_out' AND reason_code = 'DEADLINE_EXCEEDED' AND rule_id IS NULL)
        OR (outcome = 'internal_error' AND reason_code = 'INSPECTION_FAILURE' AND rule_id IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS events_ingested_at_idx ON audit.events (ingested_at);

-- SECURITY DEFINER lets the runtime role append without direct table access.
-- Deployment must ensure the function owner is a dedicated non-login role,
-- revoke PUBLIC execution, and grant EXECUTE only to the runtime identity.
CREATE OR REPLACE FUNCTION audit.append_event(
    p_request_id uuid,
    p_schema_version text,
    p_event_type text,
    p_observed_at timestamptz,
    p_decision text,
    p_rule_id text,
    p_outcome text,
    p_reason_code text,
    p_duration_ms integer,
    p_payload_bytes bigint,
    p_service_version text,
    p_event_digest bytea
) RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, audit
AS $$
DECLARE
    inserted_count integer;
    existing_digest bytea;
BEGIN
    INSERT INTO audit.events (
        request_id, schema_version, event_type, observed_at, decision,
        rule_id, outcome, reason_code, duration_ms, payload_bytes,
        service_version, event_digest
    ) VALUES (
        p_request_id, p_schema_version, p_event_type, p_observed_at, p_decision,
        p_rule_id, p_outcome, p_reason_code, p_duration_ms, p_payload_bytes,
        p_service_version, p_event_digest
    )
    ON CONFLICT (request_id) DO NOTHING;

    GET DIAGNOSTICS inserted_count = ROW_COUNT;
    IF inserted_count = 1 THEN
        RETURN true;
    END IF;

    SELECT e.event_digest INTO existing_digest
      FROM audit.events AS e
     WHERE e.request_id = p_request_id;

    -- Same event ID + same digest is an idempotent retry after ambiguous commit.
    -- Reuse of an ID for different content fails closed.
    RETURN COALESCE(existing_digest = p_event_digest, false);
END;
$$;

REVOKE ALL ON SCHEMA audit FROM PUBLIC;
REVOKE ALL ON TABLE audit.events FROM PUBLIC;
REVOKE ALL ON FUNCTION audit.append_event(
    uuid, text, text, timestamptz, text, text, text, text, integer, bigint, text, bytea
) FROM PUBLIC;
