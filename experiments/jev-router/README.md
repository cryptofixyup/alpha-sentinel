# JEV-to-Gemini reference router: probability validation repair

Status: isolated experiment with offline regression tests. Release HOLD.
No production integration or live provider evaluation is claimed.

## Historical provenance

The original recovery is preserved at commit
`480774972bbcc392c164dc9f5b89ad46edc7b935` on
`recovery/jev-router-20261024`.

| Artifact | Recorded creation date (UTC) | Original location |
| --- | --- | --- |
| `JEV-as-a-Judge-knowledge-source.md` | 2026-09-25 | Research note |
| `jev_gemini_router.py` | 2026-10-18 | LOST & FOUND |
| `test_jev_gemini_router.py` | 2026-10-18 | LOST & FOUND |

`SOURCE.sha256` is an unchanged historical manifest for the original recovered
bytes at that commit. It is not a checksum manifest for this repaired tree.
The router and tests have deliberately changed; `jev_choice_validation.py` is
new. Verify the historical manifest only in a checkout of the original recovery
commit. Do not run it against the repaired files as an acceptance check.

The research note preserves historical claims and citations. It does not
independently validate the paper, model identifiers, benchmark figures, or
current provider contracts.

## Purpose and isolation

The router classifies prompts, selects a generation model, escalates a
low-confidence simple classification, or requests review. An exact FAQ can be
answered without a provider call. Tests inject a fake transport.

There is no connection to the authorization daemon, signing, transaction
execution, or the separate approved-proposal-dispatch design. This experiment
grants no execution authority.

## Repair contract

Before Gemini routing, the response must contain exactly four route probabilities:
`simple_task`, `complex_task`, `needs_review`, and `other`.
Each must be a finite number in [0, 1], excluding booleans. Their sum must be
within an absolute tolerance of 1e-6 of one. The selected route must be the
unique probability maximum; ties and mismatches are rejected.

Confidence is independently validated as a finite number in [0, 1], excluding
booleans. No confidence=selected-probability relationship is assumed.
This is internal consistency validation, not proof of provider compatibility
or calibration.

## Offline verification

From the repository root, with Python 3.11 or later:

```bash
python -m unittest discover -s experiments/jev-router -p 'test_*.py' -v
python -m compileall -q experiments/jev-router
```

The `JEV router offline tests` workflow checks out and records the exact PR head.
It runs the original routing tests and added table-driven regressions covering
probability shapes and keys, nonfinite/out-of-range/invalid values,
normalization, ties, choice mismatch, and independent confidence.
Rejected response tests assert that no Gemini request occurs.
No provider credentials, model requests, or additional packages are needed.
Passing these mocked tests does not measure model quality.

## Merge and release gates

The experimental repair may be reviewed independently from release readiness.
Merge evidence consists of passing exact-head offline CI, review of the bounded
repair, and a conflict-free PR. The owner has removed the PR-specific signing
hold; this does not alter repository rules or make unsigned commits verified.

Before release:
- Pin and verify the JEV and Gemini model versions, endpoints, authentication,
  response contracts, and version-specific confidence semantics.
- Complete a separate held-out routing evaluation with acceptance thresholds
  defined before scoring. Report accuracy, selective risk, coverage, and
  routing cost against a stated baseline. Keep calibration and held-out data
  separate. The 0.90 confidence threshold remains an uncalibrated example.
- Preserve the transport and Gemini-response follow-up gates below.

## Known limits and follow-up gates

- The test named `test_jev_request_matches_documented_schema` checks fixture
  construction only; it is not independent provider conformance evidence.
- The HTTP helper uses default urllib redirect behavior; credential forwarding
  and destination controls need review before enabling real requests.
- The per-request timeout is not a proven total wall-clock deadline. Response
  size is bounded, but duplicate JSON keys and nonstandard numeric constants
  are not explicitly rejected by the transport parser.
- Gemini finish reasons, safety metadata and partial-response handling require
  review. Accuracy, selective risk, cost reduction and prompt-injection
  resistance have not been measured on a local held-out dataset.
- Manually invoking the CLI for a non-FAQ prompt can send that prompt to external
  providers and incur charges if credentials are configured. CI does not do so.
