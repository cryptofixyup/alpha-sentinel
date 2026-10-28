mod auth;

use axum::{
    body::{to_bytes, Body},
    extract::State,
    http::{Request, StatusCode},
    response::IntoResponse,
    routing::post,
    Json, Router,
};
use serde::{Deserialize, Serialize};
use std::{net::SocketAddr, sync::Arc, time::Duration};
use tower_http::{limit::RequestBodyLimitLayer, timeout::TimeoutLayer, trace::TraceLayer};

use alpha_sentinel_guardrail_proxy::{Decision, SentinelEngine, MAX_PAYLOAD_BYTES};
use auth::{unix_time_seconds, AuthError, HmacAuthenticator};

#[derive(Clone)]
struct AppState {
    engine: Arc<SentinelEngine>,
    authenticator: Arc<HmacAuthenticator>,
}

#[derive(Deserialize)]
struct InspectRequest {
    prompt: String,
}

#[derive(Serialize)]
struct InspectResponse {
    decision: &'static str,
    reason: &'static str,
}

fn auth_failure() -> axum::response::Response {
    (StatusCode::UNAUTHORIZED, Json(serde_json::json!({"error":"authentication failed"}))).into_response()
}

async fn health() -> impl IntoResponse {
    (
        StatusCode::OK,
        Json(serde_json::json!({"status":"ok","mode":"inspection-only"})),
    )
}

async fn inspect(State(state): State<AppState>, request: Request<Body>) -> axum::response::Response {
    // Copy header values before consuming the request body.
    let timestamp = match request.headers().get("x-sentinel-timestamp").and_then(|v| v.to_str().ok()) {
        Some(v) => v.to_owned(),
        None => return auth_failure(),
    };
    let nonce = match request.headers().get("x-sentinel-nonce").and_then(|v| v.to_str().ok()) {
        Some(v) => v.to_owned(),
        None => return auth_failure(),
    };
    let signature = match request.headers().get("x-sentinel-signature").and_then(|v| v.to_str().ok()) {
        Some(v) => v.to_owned(),
        None => return auth_failure(),
    };

    let body = match to_bytes(request.into_body(), MAX_PAYLOAD_BYTES).await {
        Ok(body) => body,
        Err(_) => return (StatusCode::PAYLOAD_TOO_LARGE, Json(serde_json::json!({"error":"request body invalid or too large"}))).into_response(),
    };
    let now = match unix_time_seconds() {
        Ok(now) => now,
        Err(_) => return (StatusCode::INTERNAL_SERVER_ERROR, Json(serde_json::json!({"error":"system clock unavailable"}))).into_response(),
    };
    match state.authenticator.verify(&timestamp, &nonce, &signature, &body, now) {
        Ok(()) => {}
        Err(AuthError::ReplayCacheUnavailable | AuthError::ReplayCacheFull) => {
            return (StatusCode::SERVICE_UNAVAILABLE, Json(serde_json::json!({"error":"authentication temporarily unavailable"}))).into_response();
        }
        Err(_) => return auth_failure(),
    }

    let request: InspectRequest = match serde_json::from_slice(&body) {
        Ok(request) => request,
        Err(_) => return (StatusCode::BAD_REQUEST, Json(serde_json::json!({"error":"invalid JSON request"}))).into_response(),
    };
    match state.engine.inspect(request.prompt.as_bytes()) {
        Decision::Allow => (
            StatusCode::OK,
            Json(InspectResponse { decision: "ALLOW", reason: "no configured signature matched" }),
        ).into_response(),
        Decision::RejectSignature => (
            StatusCode::FORBIDDEN,
            Json(InspectResponse { decision: "REJECT", reason: "configured threat signature matched; circuit opened" }),
        ).into_response(),
        Decision::RejectCircuitOpen => (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(InspectResponse { decision: "REJECT", reason: "circuit is open" }),
        ).into_response(),
        Decision::RejectOversized => (
            StatusCode::PAYLOAD_TOO_LARGE,
            Json(InspectResponse { decision: "REJECT", reason: "payload exceeds inspection limit" }),
        ).into_response(),
    }
}

#[tokio::main]
async fn main() {
    let addr: SocketAddr = std::env::var("SENTINEL_BIND")
        .unwrap_or_else(|_| "127.0.0.1:8080".to_owned())
        .parse()
        .expect("SENTINEL_BIND must be a valid socket address");
    let key = std::env::var("SENTINEL_HMAC_KEY")
        .expect("SENTINEL_HMAC_KEY must be configured; use at least 32 random bytes");
    let state = AppState {
        engine: Arc::new(SentinelEngine::new()),
        authenticator: Arc::new(HmacAuthenticator::new(key.into_bytes()).expect("SENTINEL_HMAC_KEY must contain at least 32 bytes")),
    };
    let app = Router::new()
        .route("/health", axum::routing::get(health))
        .route("/v1/agent/invoke", post(inspect))
        .with_state(state)
        .layer(RequestBodyLimitLayer::new(MAX_PAYLOAD_BYTES))
        .layer(TimeoutLayer::new(Duration::from_secs(3)))
        .layer(TraceLayer::new_for_http());

    let listener = tokio::net::TcpListener::bind(addr).await.expect("bind failed");
    eprintln!("Alpha Sentinel inspection-only prototype listening on {addr}");
    eprintln!("WARNING: this endpoint does not forward to an upstream agent.");
    axum::serve(listener, app)
        .with_graceful_shutdown(async { let _ = tokio::signal::ctrl_c().await; })
        .await
        .expect("server failed");
}
