# ADR-014: Package Dependency Direction

## Decision:
Core packages (`config`, later `logging`) must not depend on higher-level application packages.

## Reason:
Maintain a clean dependency graph, improve testability, and eliminate circular dependencies.