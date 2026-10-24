# Recovered JEV-to-Gemini reference router

Status: recovered experiment, offline unit tests only. No production integration.

This directory preserves three previously supplied artifacts byte-for-byte:

| Artifact | Recorded creation date (UTC) | Original location |
| --- | --- | --- |
| `JEV-as-a-Judge-knowledge-source.md` | 2026-09-25 | Research note |
| `jev_gemini_router.py` | 2026-10-18 | LOST & FOUND |
| `test_jev_gemini_router.py` | 2026-10-18 | LOST & FOUND |

`SOURCE.sha256` records the recovered bytes. The research note preserves historical
claims and citations; importing it does not independently validate the paper,
model names, reported benchmark numbers, or current provider API contracts.

## Purpose and isolation

The router classifies a prompt and selects a generation model, escalates a
low-confidence simple classification, or requests review. Its exact FAQ can be
answered without any provider call. The recovered tests inject a fake transport.
This differs from the existing `typesafe_labeler.py`, which classifies security
concerns using the TypeSafe SDK. Neither component grants execution authority.

There is no connection to the authorization daemon, signing, transaction
execution, or the separate approved-proposal-dispatch design. No existing
runtime file was modified for this recovery.

## Offline verification

From the repository root, with Python 3.11 or later:

```bash
python -m unittest discover -s experiments/jev-router -p 'test_*.py' -v
python -m compileall -q experiments/jev-router
(cd experiments/jev-router && sha256sum --check SOURCE.sha256)
```

The dedicated `JEV router recovery` workflow checks out the exact PR head and
runs all 11 recovered tests with Python 3.11. It needs no provider credentials,
external model requests, or additional Python packages. Existing repository CI
also runs independently. Test totals from overlapping suites must not be added.

A red-before-green implementation test is not applicable to this byte-preserving
recovery: behavior is unchanged. Verification consists of source hash equality,
execution of the recovered tests, compilation, and repository CI. The tests'
existence does not establish that they ran successfully before this recovery.

## Known limits and follow-up gates

- The 0.90 threshold is an uncalibrated example. Model identifiers, endpoint
  availability, authentication and response contracts have not been live-tested.
- The test named `test_jev_request_matches_documented_schema` checks fixture
  construction only; it is not independent provider conformance evidence.
- Confidence is validated, but the returned probability distribution is not
  checked for completeness, normalization or agreement with the selected label.
- The HTTP helper uses default urllib redirect behavior; credential forwarding
  and destination controls need review before enabling real requests.
- The per-request timeout is not a proven total wall-clock deadline. Response
  size is bounded, but duplicate JSON keys and nonstandard numeric constants are
  not explicitly rejected by the transport parser.
- Gemini finish reasons, safety metadata and partial-response handling require
  review. Neither accuracy, selective risk, cost reduction nor prompt-injection
  resistance has been measured on a local held-out dataset.
- Manually invoking the CLI for a non-FAQ prompt can send that prompt to external
  providers and incur charges if credentials are configured. CI does not do so.

Preserve this baseline when hardening: add a test that reproduces each concrete
defect before changing behavior, and document deliberate changes to source hashes.
