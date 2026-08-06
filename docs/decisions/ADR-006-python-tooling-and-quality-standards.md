# ADR-006: Python Tooling and Quality Standards

## Status
Accepted

## Context
Instead of accepting default settings, I'd like us to agree on a strict quality bar.
### Ruff
- enable most checks
- ignore only rules we intentionally disagree with

### Black
Standard configuration.

### mypy
I'd like to run in strict mode as much as practical. Because it catches a surprising number of bugs early. We may relax a few checks around third-party libraries that lack type hints.

## Decision
We've made a long-term architectural decision to standardize on `uv`, `black`, `ruff`, `mypy`, and `pytest` as part of the project's development workflow. This affects every future contribution and defines the project's quality gate, so it's worth documenting as an ADR rather than leaving it implicit.