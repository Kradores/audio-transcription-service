# ADR-016: Application Composition Root

## Context
The project now has a complete configuration subsystem. As more services (logging, database, Whisper, audio capture, API, MCP) are introduced, we need a single place to compose dependencies without relying on global state.

## Decision
Introduce an `Application` class as the composition root. All long-lived services are created during application startup and owned by this object. Entry points (CLI, API, MCP server) delegate to the composition root instead of constructing dependencies themselves.