# State

This boundary owns the security-critical state model.

State must be durable and transition only through the lifecycle mechanism. Callers must not receive a general-purpose mutation interface.
