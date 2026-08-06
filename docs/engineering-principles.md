# Engineering Principles

## Reliability over cleverness
Prefer code that is obvious over code that is clever.

## Small components
A class should have one responsibility.

## Constructor Injection
Dependencies are provided from outside.
Avoid hidden dependencies.

## Configuration-driven
Avoid magic values.
Prefer configuration.

## Strong typing
Use type hints everywhere.
Run mypy.

## Testability
Every public component should be testable.
Avoid designs that require real hardware during unit tests.

## Structured logging
Every major component logs meaningful events.

## Resilience
Recover automatically whenever possible.
The service should not require manual restarts for expected failures.

## Observability
If something can fail, we should be able to understand why.

## Incremental delivery
Every sprint ends with a working application.

## Architecture before optimization
Don't optimize prematurely.
Measure first.

## Make invalid states impossible whenever practical
For example, instead of:
```
class Transcript:
    text: str | None
    language: str | None
```
where every caller has to check for None, we'd rather design our pipeline so that a Transcript object only exists once it has valid data. Fewer impossible states means fewer bugs.

## When a decision becomes an architectural decisions
If a discussion ends with "we've decided to do X", we ask ourselves: "Will someone wonder why in six months?" If the answer is yes, it deserves an ADR.