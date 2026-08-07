# ADR-011: Typed Configuration System

## Status
Approved

## Decision
We've decided on a layered, strongly-typed configuration architecture based on Pydantic models, with centralized loading, validation at startup, and dependency injection. This affects every component in the application and is a foundational architectural decision.