# Native Android Evidence Slice

Purpose: a small, independently auditable native Android subsystem demonstrating Kotlin, Jetpack Compose, Coroutines, StateFlow, bounded local AI/interpretability execution, telemetry, security controls, and tests.

## Scope

This subsystem is intentionally isolated from the existing application until its native boundary is proven.

### P0
- Kotlin + conventional Gradle Android project
- Immutable request/result contracts
- Explicit execution state machine
- Structured coroutine execution
- Timeout and cancellation
- Bounded local inference/interpretability workload
- Result validation
- Minimal permissions and no unnecessary external capabilities
- Latency/memory/status telemetry
- Security and failure-path tests
- CI build/test/static analysis

### P1
- Narrow React Native bridge after P0 is green
- Measured performance report

## Security boundary

The native execution component must not receive credentials, signing authority, arbitrary filesystem access, shell/process execution, or network access unless a later requirement is explicitly reviewed and justified.

The UI observes state; it does not own execution authority.

## Evidence rule

Claims in this repository must be supported by source, tests, CI output, or measured telemetry. No benchmark, production, or deployment claim is made until demonstrated.
