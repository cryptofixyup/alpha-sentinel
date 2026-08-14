# Lifecycle

The lifecycle is the deterministic state-transition boundary.

Every transition must:

1. load the current durable state;
2. validate the proposal and policy constraints;
3. determine the single allowed next state;
4. persist the transition atomically;
5. expose the resulting state without granting mutation authority.

Invalid, stale, duplicated, or unauthorized transitions must fail closed.
