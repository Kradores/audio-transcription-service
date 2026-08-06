# ADR-009: Code Quality Gates and Development Tooling

## Status
Accepted

## Context
Why we've chosen automated formatting, linting, static type checking and tests as mandatory quality gates.

### Ruff
- Enable almost all rules.
- Ignore only rules we consciously disagree with.

I don't want a huge ignore list.

### Black
Use defaults.
One less thing to think about.

### mypy
I'd like to be fairly strict.
Not "maximum pain" strict, but enough to catch real mistakes.

Examples:

- Missing return types.
- Incorrect optional handling.
- Invalid assignments.

We can relax specific rules if third-party libraries make them impractical.

### Pre-commit hooks
Every commit automatically runs:
```
black

↓

ruff

↓

mypy

↓

pytest
```

## Decision
Use Ruff, Black, mypy. Add pre-commit hooks.
