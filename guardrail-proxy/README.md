# Alpha Sentinel Guardrail Proxy (prototype)

A small Rust/Axum inspection service demonstrating a bounded deterministic policy gate.

## Scope and limitations

- This is an **inspection-only prototype**, not a complete reverse proxy: it does not forward allowed requests to Gemini or another upstream.
- Signature matching is a demonstration heuristic, not a comprehensive prompt-injection detector.
- A process-wide breach latch rejects later requests until an operator-controlled recovery is implemented. The library reset method is not exposed over HTTP.
- No authentication, durable audit log, upstream authorization, or operational key isolation is implemented.
- The endpoint returns ALLOW when no configured signature matches. That is not proof that a request is safe.
- No sub-5-nanosecond or zero-allocation claim is made for the complete service.

## Run

```sh
cargo test --manifest-path guardrail-proxy/Cargo.toml
cargo run --manifest-path guardrail-proxy/Cargo.toml
```

By default, binds to `127.0.0.1:8080`. Set `SENTINEL_BIND` to override. Do not bind to a public interface without adding authentication and deployment controls.

## HTTP contract

- `GET /health`: health check.
- `POST /v1/agent/invoke`: JSON body `{"prompt":"..."}`; inspects the prompt and returns ALLOW/REJECT. Despite the route name, this prototype does not invoke an upstream agent.

Run the real HTTP regression harness in a second terminal:

```sh
python -m pip install requests
python guardrail-proxy/tests/fuzz_harness.py
```

The harness is a fixed regression suite, not coverage-guided fuzzing. The process-wide latch means run the suite against a fresh process each time.

## Security notes

The scanner performs bounded ASCII case-insensitive substring matching without heap allocation in the inspection function. It does not normalize Unicode, decode obfuscated content, join streaming chunks, inspect tool arguments, or enforce tool permissions. Request JSON parsing and HTTP middleware can allocate; therefore no whole-request zero-allocation guarantee is made. Entropy is deliberately excluded from authorization decisions.
