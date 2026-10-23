# Alpha Sentinel — CI evidence register (2026-10-16)

## Scope and provenance

Repository: `cryptofixyup/alpha-sentinel`. This is a documentation-only snapshot based on GitHub API workflow-run metadata, individual job steps and raw job logs inspected on 2026-10-16. It is **not** a new test run or an assertion of full post-merge certification.

- `main` at report preparation: `b9f2d8d815a13362717e6d3eaf36cdb0d6650112`.
- PR #13, Signed Result Verification v1: **merged** 2026-08-24 08:59:56 UTC; merge commit `e30ee03bf998398261a4e28d387e46cc212eac58`; [PR](https://github.com/cryptofixyup/alpha-sentinel/pull/13).
- Three successful `pull_request` workflow runs associated with **PR #46**, on head `3241a069b6289e2372ad78725de121aa57e0e3dd`, created 2026-10-16 10:31:30 UTC. This SHA is **not** the above `main` SHA.

## Verified CI execution (PR #46 SHA `3241a069...`; not PR #13)

| Workflow | Run ID / job ID | Observed job result | Log-supported tests |
|---|---|---|---|
| [Signed Result Verification v1](https://github.com/cryptofixyup/alpha-sentinel/actions/runs/38887797555) | `38887797555` / `116929689224` | completed: success | Node TAP: **14 passed, 0 failed, 0 skipped** |
| [Zernio Router Adapter v1](https://github.com/cryptofixyup/alpha-sentinel/actions/runs/38887797425) | `38887797425` / `116929689320` | completed: success | Node TAP: **33 passed, 0 failed, 0 skipped** |
| [ML Pipeline CI](https://github.com/cryptofixyup/alpha-sentinel/actions/runs/38887797430) | `38887797430` / `116929689341` | completed: success | Node security/lifecycle suite: **31 passed, 0 failed, 0 skipped**; Python tests, Zernio invariants, and benchmark steps marked successful. |

The signed-result logs include tests for forged/incorrect signatures, stale and future results, proposal/external execution/request and platform/account binding, duplicate rejection across restart, unknown proposals and concurrency accepting exactly one result. Zernio logs include timelock rejection, approval and transaction binding, signed-webhook checks, audit tampering detection and lifecycle transition rejection. These are *tested cases*, not a proof of complete security.

ML Pipeline benchmark logged a nonfatal PyTorch warning that NumPy was unavailable. The benchmark step nevertheless concluded successfully.

## Mainline evidence, distinct from PR evidence

At `b9f2d8d815a13362717e6d3eaf36cdb0d6650112`, the GitHub commit check-runs API reported successful checks named `deploy`, `report-build-status`, `coverage`, `build`, `Python 3.11` and `boundary-tests`.

At PR #13 merge commit `e30ee03bf998398261a4e28d387e46cc212eac58`, the same API reported successful checks `deploy`, `report-build-status`, `Python 3.11` and `build`.

**Neither set constitutes verified execution of all three named workflows at that exact mainline SHA.** Do not transfer a PR-head result to another commit.

## Evidence classification and outstanding gate

- **VERIFIED:** PR #13 merged; separately, all three workflows successful on PR #46 SHA `3241a069...`, with job-level logs inspected. These runs do **not** establish CI execution on PR #13's head `9eb88e3a9603202a090765e66b7e11d0a19829cf`.
- **VERIFIED:** identified mainline commit check conclusions above.
- **UNVERIFIED:** successful execution of Signed Result Verification v1, Zernio Router Adapter v1 and ML Pipeline CI **together against exact current `main`**.
- **NOT CLAIMED:** an independently verified exact-mainline authorization/security release gate.

**Gate: PR #13 MERGED — THREE NAMED WORKFLOWS PASSED ON PR #46 SHA `3241a069...` — EXACT-MAINLINE ATTESTATION OPEN.**

Required next step: run or establish the three workflow executions on the chosen immutable target SHA; save run IDs, event, `head_sha`, conclusions, job logs and test counts. A subsequent documentation commit changes the branch SHA and cannot inherit test evidence automatically.

This register does not modify code, workflows, CI rules, authorization or timelock controls.
