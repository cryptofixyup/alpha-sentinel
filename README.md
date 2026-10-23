# Alpha Sentinel

**AI security and authorization framework for autonomous agents**

Alpha Sentinel is a security-first, deterministic control plane designed to separate AI reasoning from execution authority.

> **Core principle**  
> AI proposes. Deterministic controls decide. Cryptography binds. Isolation signs. Blockchain verifies.

The principle describes the target architecture. It is **not** a claim that every stage is operationally integrated or production-verified.

## Why Alpha Sentinel?

Autonomous AI agents can interact with consequential systems, including blockchain, DeFi, and financial automation. Model-generated decisions must not serve as the final authorization boundary.

Alpha Sentinel explores independently enforceable deterministic controls before consequential actions are authorized.

## Key Capabilities

- Deterministic risk assessment and policy enforcement
- Transaction simulation and re-simulation gates in the authorization pipeline
- Transaction-bound approvals and timelock enforcement
- An isolated-signer interface with a fail-closed default implementation; operational key isolation is not yet demonstrated
- Explicit lifecycle state machines, persistence, and recovery tests
- Audit and signed-evidence verification components, with end-to-end verification still under evaluation

## Architecture Highlights

| Layer | Responsibility and current boundary |
| --- | --- |
| Policy Engine | Deterministic risk and authorization decisions |
| Simulation Boundary | Validate a transaction using an injected simulator before signing; real-chain guarantees require a trusted implementation |
| Approval Binding | Bind approval to exact proposal and transaction digests |
| Isolated Signing | Signer abstraction exists; default signer refuses to sign, and operational isolated signing is not demonstrated |
| Lifecycle State Machine | Explicit transitions and recovery/replay controls |
| Audit & Verification | Evidence checks and regression tests; live broadcast and independent receipt verification are not demonstrated end to end |

## Current Status and CI Evidence

Alpha Sentinel is under active development. Core control-plane components, authorization boundaries, lifecycle handling, and regression tests are implemented. Production readiness and full end-to-end security guarantees remain validation objectives.

At signed default-branch commit `b9f2d8d815a13362717e6d3eaf36cdb0d6650112`, GitHub Actions recorded:

- **171/171** top-level Node tests passing
- **172/172** recursive Node tests passing (overlapping with the top-level suite; do not add the counts)
- **26/26** Python security-boundary tests passing

Evidence: [Coverage v1](https://github.com/cryptofixyup/alpha-sentinel/actions/runs/38478766114) · [security-boundary](https://github.com/cryptofixyup/alpha-sentinel/actions/runs/38478764060) · [ML Pipeline CI](https://github.com/cryptofixyup/alpha-sentinel/actions/runs/38478764236).

[PR #50](https://github.com/cryptofixyup/alpha-sentinel/pull/50), merged as `7504edb09418766a5046a9789c879a01a6549d8d`, adds five bounded Python authorization regression tests and a dedicated Python 3.11 CI workflow. The dedicated [PR workflow](https://github.com/cryptofixyup/alpha-sentinel/actions/runs/40010667592) passed **5/5** tests. These tests use a recording signer test double, not an isolated production signer.

**Not yet demonstrated:** operational isolated key custody, a fully integrated live broadcast-and-receipt verification path, or end-to-end authorization guarantees under adversarial production conditions.

## Repository Structure

- `core/` — Control-plane lifecycle and daemon components
- `security/` and `security_boundary/` — Security evidence and Python authorization boundary
- `simulation/` — Simulation boundary components
- `state/` — State and lifecycle persistence components
- `tests/` — Automated regression and security tests
- `.github/workflows/` — CI pipelines and dedicated authorization fixture gate

## Research Focus

1. **Deterministic Agent Authorization** — Test enforceable policies independently of model behavior
2. **Adversarial Robustness** — Evaluate prompt injection, malformed outputs, and attempts to bypass execution controls
3. **Reproducible Security Evidence** — Publish evaluation fixtures, regression coverage, and independently reviewable results

## Getting Started

```bash
git clone https://github.com/cryptofixyup/alpha-sentinel.git
cd alpha-sentinel

# Run the bounded authorization fixture (requires Python 3.11 and pytest)
python -m pip install pytest
python -m pytest -q tests/test_grant_authorization_fixture.py

# Run the existing Python security-boundary suite
python -m pytest -q tests/test_security_boundary.py
```

These are test fixtures. They do not perform production signing or live blockchain broadcasts.

## License

No repository license is currently declared in GitHub metadata, and no root `LICENSE` file was found during this update. Do not assume the source is licensed for unrestricted reuse. A license must be selected and added by the repository owner.

## Author

Piotr Kozłowski  
Founder, CryptoFixYup  
Independent software architect focused on deterministic systems, cryptographic integrity, and evidence-based security for autonomous AI.
