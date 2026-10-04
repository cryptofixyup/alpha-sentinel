# AEGIS Integration — BLOCKED DRAFT

Status: **BLOCKED. DO NOT INTEGRATE YET.**

The private AEGIS repository is in an intentional review/wrestling period.

Alpha Sentinel integration must not begin merely because the conceptual architecture fits.

## Entry Gate

Before integration design is promoted:

- the 72-hour review period has completed;
- remaining AEGIS verification has been performed;
- evidence distinguishes local tests, actual engine/Sentinel execution and CI;
- the exact accepted AEGIS commit is identified;
- unresolved discrepancies remain explicit.

## Intended Boundary After Gate

AEGIS -> EvidenceEnvelope -> Trust Admission / Sentinel policy context

AEGIS contributes session-integrity and correlation evidence.

It does not become an authorization authority.

No Alpha Sentinel runtime code is changed by this document.
