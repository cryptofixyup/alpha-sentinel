# Common Evidence Model

Status: specification draft.

Subsystems communicate security-relevant facts through evidence rather than hidden trust.

## EvidenceEnvelope

Conceptual fields:

- source
- observation
- observed_at
- artifact_hash
- collector
- confidence
- classification
- related_decision
- verification_status
- provenance

An evidence item is not an authorization decision.

## Evidence Rules

- Preserve raw observation separately from interpretation.
- Preserve event time separately from documentation/retrieval time.
- Hash artifacts where stable bytes exist.
- Record missing data as missing, not as a favorable inference.
- Conflicting evidence remains visible.
- Incident monetary values retain their original valuation timestamp/context; current asset prices must not silently rewrite historical figures.

See `ASSURANCE_LEVELS.md` for reporting requirements.
