# Incident-Derived Regression Registry

Status: candidate regression requirements.

Incident facts and root-cause attribution require source-backed evidence records before being promoted to verified regressions.

## IR-001 — Callable Module Without Intended Authority

Candidate property:

Technical callability or adapter capability must never substitute for explicit authority.

Regression direction:

An otherwise valid module/caller lacking exact scoped authority is denied before consequence.

## IR-002 — Functional but Wrong Substrate

Candidate property:

Successful RPC/network interaction and claimed chain identity must not establish substrate identity.

Regression direction:

Claimed and independently attested substrate identity mismatch causes DENY or QUARANTINE before consequential interaction.

## IR-003 — Valid Credential/Session, Invalid Intent or Context

Candidate property:

Credential validity does not alone establish human intent or transaction authority.

Regression direction:

A technically valid session attempting an unbound consequential command is denied.

## IR-004 — Untrusted Code Presented as a Legitimate Workflow

Candidate property:

Repositories, packages and interview artifacts are untrusted until admitted and isolated.

Regression direction:

Unknown executable artifacts receive no host secrets, wallet credentials or unrestricted host/network capability by default.

## Evidence Rule

Names, losses, root causes and incident-time valuations belong in source-backed evidence snapshots.

Market-price changes must not rewrite historical valuations used by the original evidence.
