# Router Adapter Boundary

Routers and external integrations are adapters, not authorities.

This boundary may receive an already-authorized lifecycle result and perform bounded external interaction. It must not approve transitions, mutate security-critical state, create authorization authority, or bypass lifecycle validation.

Production RPC, signing, custody, and broadcaster implementations are intentionally excluded from this skeleton.
