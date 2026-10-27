# Guardrail Proxy Security Review

**Review scope:** `guardrail-proxy/` at the prototype PR head. This is a source-level review, not a penetration test or production certification.

## Current decision

**Do not deploy as a public or production agent proxy.** The service is an inspection demonstration only. The HTTP endpoint does not forward requests upstream. The local Termux run reported five Rust unit tests and three HTTP regression cases passing; those results do not establish production security.

## Findings

| ID | Severity | Finding | Consequence | Required disposition |
|---|---|---|---|---|
| GP-01 | Critical blocker for public deployment | No caller authentication or authorization. | Any reachable caller can submit requests and trigger the process-wide breach latch. | Require authenticated identity and authorization before inspection; default deny when credentials are absent or invalid. |
| GP-02 | High | A single matching substring opens a process-wide latch permanently until restart; the endpoint is unauthenticated. | A caller can deny service to all later requests. False positives also cause service-wide outage. | Define authenticated operator recovery, rate limiting, and a documented circuit-breaker policy; test concurrency and recovery. |
| GP-03 | High / missing feature | No upstream forwarding exists. | An ALLOW response does not invoke an agent and cannot protect a real upstream execution path. | Implement fixed, allowlisted upstream destinations; prevent arbitrary URL forwarding/SSRF; enforce connect/read/total timeouts and bounded response sizes. |
| GP-04 | High / missing feature | No durable audit trail. | Decisions, identity, correlation, and recovery cannot be independently reconstructed after restart. | Persist structured decision events with sequence/correlation identifiers, outcome, rule ID, and timestamp; exclude secrets and prompt content by default; define retention and write-failure policy. |
| GP-05 | High | Scanner is a small list of ASCII case-insensitive substrings. | Unicode variants, encoding, paraphrase, split chunks, tool arguments, and other prompt-injection forms can evade it; benign text may trigger false positives. | Treat the scanner as a narrow deterministic rule, not a general detector; add adversarial and false-positive corpus tests and inspect every execution-relevant field. |
| GP-06 | Medium | Oversize request handling depends on middleware and handler limits. | Behavior may differ between raw JSON body size and the decoded `prompt` field; exact error response may be middleware-generated. | Add integration tests for raw body and decoded prompt boundaries, malformed JSON, missing prompt, and timeout behavior. |
| GP-07 | Medium | Reset exists as a public library method (not exposed over HTTP). | Any future caller in-process can clear the latch without an enforced authorization boundary. | Keep reset behind a narrow authenticated operator API/service boundary and emit an audit event; document process restart as the current prototype recovery path. |
| GP-08 | Medium | Health endpoint exposes unauthenticated service status. | Usually low sensitivity, but should be restricted or deliberately classified for production deployments. | Separate liveness/readiness and define network exposure. |

## Existing controls observed

- Loopback-only default bind (`127.0.0.1:8080`).
- Request-body limit middleware and a three-second middleware timeout.
- Scanner rejects payloads above 64 KiB and uses a monotonic atomic breach latch.
- HTTP harness exercises benign allow, mixed-case signature rejection, and post-breach rejection.
- README explicitly labels the service inspection-only and disclaims whole-service zero-allocation and sub-5-nanosecond claims.

## Acceptance gates

- [ ] CI runs formatting, Rust tests, release compilation, and the HTTP regression harness.
- [ ] CI results are green on the PR head.
- [ ] Authentication/authorization and safe upstream forwarding are implemented and integration-tested.
- [ ] Durable, secret-minimizing audit events and write-failure behavior are implemented and tested.
- [ ] Recovery, rate limiting, malformed/oversized input, timeout, false-positive, and bypass behavior are covered.
- [ ] Independent security review and deployment threat model completed.

**Conclusion:** Local tests provide useful evidence for the narrow prototype. They do not justify production deployment or a claim that the service is a complete security proxy.
