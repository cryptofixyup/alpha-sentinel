# Core Tests

Tests must prove security invariants, not merely happy-path behavior.

Initial test categories:

- illegal transition rejection;
- stale proposal rejection;
- duplicate/replay rejection;
- authorization-boundary enforcement;
- deterministic transition results;
- durable-state consistency;
- router isolation from authorization decisions.
