use axum::{
    extract::State,
    http::StatusCode,
    response::IntoResponse,
    routing::post,
    Json, Router,
};
use serde::{Deserialize, Serialize};
use std::{net::SocketAddr, sync::Arc, time::Duration};
use tower_http::{limit::RequestBodyLimitLayer, timeout::TimeoutLayer, trace::TraceLayer};

use alpha_sentinel_guardrail_proxy::{Decision, SentinelEngine, MAX_PAYLOAD_BYTES};

#[derive(Clone)]
struct AppState { engine: Arc<SentinelEngine> }

#[derive(Deserialize)]
struct InspectRequest {
    prompt: String,
}

#[derive(Serialize)]
struct InspectResponse {
    decision: &'static str,
    reason: &'static str,
}

async fn health() -> impl IntoResponse {
    (StatusCode::OK, Json(serde_json::json!({"status":"ok","mode":"inspection-only"})))
}

async fn inspect(
    State(state): State<AppState>,
    Json(request): Json<InspectRequest>,
) -> impl IntoResponse {
    match state.engine.inspect(request.prompt.as_bytes()) {
        Decision::Allow => (StatusCode::OK, Json(InspectResponse { decision: "ALLOW", reason: "no configured signature matched" })),
        Decision::RejectSignature => (StatusCode::FORBIDDEN, Json(InspectResponse { decision: "REJECT", reason: "configured threat signature matched; circuit opened" })),
        Decision::RejectCircuitOpen => (StatusCode::SERVICE_UNAVAILABLE, Json(InspectResponse { decision: "REJECT", reason: "circuit is open" })),
        Decision::RejectOversized => (StatusCode::PAYLOAD_TOO_LARGE, Json(InspectResponse { decision: "REJECT", reason: "payload exceeds inspection limit" })),
    }
}

#[tokio::main]
async fn main() {
    let addr: SocketAddr = std::env::var("SENTINEL_BIND")
        .unwrap_or_else(|_| "127.0.0.1:8080".to_owned())
        .parse().expect("SENTINEL_BIND must be a valid socket address");
    let state = AppState { engine: Arc::new(SentinelEngine::new()) };
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
    axum::serve(listener, app).with_graceful_shutdown(async {
        let _ = tokio::signal::ctrl_c().await;
    }).await.expect("server failed");
}
