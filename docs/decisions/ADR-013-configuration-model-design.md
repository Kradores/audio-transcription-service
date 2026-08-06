# ADR-012: Configuration Model Design

## Decision
- Nested immutable Pydantic models.
- Validation at the configuration boundary.
- Enums for constrained values.
- `pathlib.Path` for filesystem paths.
- No loading logic inside models.

This ADR captures the long-term shape of the configuration layer and is unlikely to change often.