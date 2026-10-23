# Alpha Sentinel Invariants

Status: normative architecture requirements. Runtime enforcement must be demonstrated separately.

1. **Capability != Authority** — technical ability to perform an operation does not authorize it.
2. **Connectivity != Identity** — a responding endpoint is not proof that it is the intended endpoint.
3. **Credentials != Intent** — a valid credential, token, session or signature does not alone establish intended authority.
4. **Admission != Permanent Trust** — admission is scoped, contextual and expiring; material changes require re-attestation.
5. **Execution != Verified Success** — expected postconditions require independent verification.

Additional constraints:

- Intelligence may propose; deterministic controls decide.
- No component may convert recognition, connectivity, credential possession, technical capability, or successful execution into authority by itself.
- A component may not approve or verify its own consequential action without an independent control/evidence boundary.
- Authorization must bind to the exact relevant artifact/context, not a mutable description of it.
- Evidence classifications and assurance levels must not be upgraded without corresponding evidence.
