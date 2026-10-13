# Assurance Levels

Status: normative reporting vocabulary.

Use the highest level actually supported by evidence:

- **SPECIFIED** — requirement exists in documentation.
- **IMPLEMENTED** — code exists; execution is not implied.
- **LOCALLY_TESTED** — identified local test command/result exists.
- **CI_VERIFIED** — identified CI run verifies the exact commit.
- **EXTERNALLY_REPLAYED** — behavior is reproduced against an external or independent environment/engine.
- **PRODUCTION_DEMONSTRATED** — identified production evidence demonstrates the property under stated conditions.

Never collapse these levels into "done" or "safe".

Every claim should identify the artifact/commit and evidence source needed to reproduce its assurance level.
