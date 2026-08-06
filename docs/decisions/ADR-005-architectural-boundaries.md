# ADR-005 — Architectural Boundaries
## Decision
Use abstractions only at architectural boundaries.

### Example
```
ADR-005

Title

Use Protocols only for replaceable infrastructure.

Decision

Protocols will only be introduced for components that:

- have multiple implementations
- or significantly improve testability

Examples

✓ AudioCapture

✓ Repository

✓ Transcriber

Not

✗ HealthController

✗ ConfigLoader

✗ Logger
```