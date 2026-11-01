# Alpha Sentinel — Authorization Boundary Evidence Report v1

**Status:** PARTIAL — NOT A RELEASE CERTIFICATION  
**Repository:** `cryptofixyup/alpha-sentinel`  
**Inspected revision:** `d64f2482739959282eaa569d6057894d4def6b19`

## Executive finding

Source inspection identifies meaningful fail-closed authorization controls. Approval is bound to both the proposal digest and transaction digest, and the execution path validates those bindings again. The pipeline blocks progression on simulation failure, missing or invalid approval, expiry, and a previously recorded signing attempt.

This is not evidence of production readiness. The default signer is disabled unless an isolated signer is configured. The bounded authorization fixture uses a recording test double, not an operational isolated signer. Broadcast and independent receipt verification remain interfaces; a complete live end-to-end integration was not demonstrated.

**Disposition: HOLD on production-readiness claims.**

## Scope and provenance

This is a source-level inspection of the revision above. No fresh tests were run while preparing this report. The following are Git blob identifiers, not independently calculated SHA-256 file hashes:

| Path | Git blob SHA |
|---|---|
| README.md | `d85743611a2a1ca8c76008df79737d760a5b8472` |
| tests/test_grant_authorization_fixture.py | `d011eaf0a9c4706bdaeb80355d4bc83e794dc33a` |
| tests/test_security_boundary.py | `b6d2558a1b563b2dd94f629b19e20507554e506c` |
| security_boundary/approval.py | `f30c3a9a8d03b4a8d6352c38bb274a0dba05b852` |
| security_boundary/execution.py | `bccd92373a6cde3b0bbbd1f46c2a464bb481ed70` |
| security_boundary/signer.py | `6f4be91dca5222b3f25d7ca379f59137a77c19e7` |
| security_boundary/pipeline.py | `58fe24c7fca1759356b6f1deec8dc08e35d3078d` |
| security_boundary/models.py | `e56f61caf97c29dfd83cff1667e33cc163eb2c7f` |
| security_boundary/store.py | `604ecfdf55f5074cb9520004e02c88341c04e699` |

## Test-source evidence

The bounded authorization fixture contains five test functions covering authorization/replay, simulation failure, approval mismatch, altered signed-envelope rejection, and the disabled default signer. It uses `RecordingTestSigner`, a test double rather than an isolated production signer.

The security-boundary fixture contains 23 test functions; one is parameterized with four cases. These are source counts, not a claim that 23 test cases were freshly executed.

The README records historical results at commit `b9f2d8d815a13362717e6d3eaf36cdb0d6650112`: 171/171 top-level Node tests, 172/172 recursive Node tests (overlapping totals; do not add them), and 26/26 Python security-boundary tests. These historical claims were not rerun for this report.

## Source findings

- Approval validation checks both proposal and transaction digests.
- The execution path checks the approval binding again.
- The default `DisabledSigner` fails closed with the message `signing disabled: isolated signer not configured`.
- The pipeline blocks failed simulation, absent or invalid approval, expired proposals, and already-claimed signing attempts.
- The proposal store persists the proposal/transaction pair, a fingerprint, and a signing-attempt flag.
- The pipeline may reach a `SIGNED` state; this does not prove network broadcast or independent on-chain verification.
- `BroadcastGateway` and `Verifier` are abstract interfaces in the inspected source.

## Not demonstrated

- Operational isolated key custody or production signing.
- Fully integrated live transaction broadcast.
- Independent end-to-end receipt verification.
- Production peer authentication and deployment hardening.
- Fresh passing tests tied to this inspected revision.
- A complete machine-readable failure-reporting contract for every rejection path.

The README itself distinguishes the target architecture from behaviour that is operationally integrated and production-verified. Preserve that distinction in external claims.

## Recommended bounded repair

Formalize authorization failure and denial reporting with stable machine-readable result codes. Add regression tests for simulation failure, absent/denied/mismatched/expired approval, replay or already-claimed attempts, and signer unavailability. Verify that rejected requests do not reach the signer or transition to a signed state. Preserve existing fail-closed controls. Keep this repair separate from implementing a production isolated signer.

## Release gates

1. Evidence the isolated-signing integration, key custody boundary, and fail-closed behaviour.
2. Complete the stable rejection-result contract and regression coverage.
3. Demonstrate the integrated broadcast implementation, including network and retry behaviour.
4. Demonstrate independent receipt verification against the expected transaction and network.
5. Capture fresh CI results tied to the exact candidate commit.
6. Document peer authentication, secrets handling, monitoring, and operational response.

A passing unit-test suite alone is not acceptance of the production boundary.

## Evidence classification

| Statement | Classification |
|---|---|
| Digest binding and revalidation | Verified by source inspection |
| Default signer fails closed | Verified by source inspection |
| Pipeline blocks inspected rejection conditions | Verified by source inspection |
| Five authorization test functions and 23 security-boundary test functions | Verified by source inspection |
| README historical test totals | Historical claim; not rerun |
| Production isolated signing | Not demonstrated |
| Integrated broadcast and independent verification | Not demonstrated |
| Fresh CI for this revision | Not checked |

**Final status: PARTIAL — NOT A RELEASE CERTIFICATION.** This report does not certify deployment, infrastructure, key custody, or production operation.
