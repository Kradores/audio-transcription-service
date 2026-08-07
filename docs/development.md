## HOW TO START
```
git clone <repo>
```
```
cd audio-transcription-service
```
```
uv sync
```

## Definition of Done (DoD)
Before we consider a task complete, we should be able to answer "yes" to something like:
- Requirements implemented
- Unit tests added
- Integration tests added (if applicable)
- Logging added
- Configuration added (if needed)
- Documentation updated
- No linting/type-checking issues
- Commit message follows Conventional Commits
It's a simple checklist, but it prevents the "I'll add tests later" or "I'll document it later" trap.

## ADRs
These are project-specific decisions.

Examples:
- Why Faster-Whisper?
- Why SQLite?
- Why queues?
- Why WASAPI?

ADRs explain why a particular decision was made and can evolve if the project changes.

## Engineering Principles
These are timeless.

## Our workflow from now on
We now have a very clear process:

- We discuss a feature.
- We agree on the design.
- Decide whether:
    1. 🟢 No ADR needed — implementation detail.
    2. 📘 ADR recommended — architectural decision.
- If needed, create/update the ADR.
- We implement.
- We test.
- We update the relevant documentation (if needed).
- We commit.

## About the code itself

From this point onward, present code like a senior engineer opening a pull request:

- specify the file being implemented.
- explain why the code is written that way.
- point out any trade-offs.
- suggest improvements if I see them.
- recommend tests before moving on.

## Code Review Checklist

For every implementation we'll review:

- Correctness
- Readability
- Maintainability
- Testability
- Type safety
- Performance (when relevant)
- Future extensibility
- Consistency with our architecture

If something can be improved, we'll improve it immediately instead of accumulating technical debt.

## Before every commit/merge, ask yourself these four questions:

- Does it compile?
- Does it pass tests?
- Would I understand this in six months?
- Would I approve this if it came from someone else?

If the answer to any of them is "no," we improve it before committing.

It's a simple checklist, but it's remarkably effective at maintaining quality.

## Coding Standards
- Import order (standard library → third-party → local)
- One responsibility per class
- Immutable configuration models
- Logical field ordering (not alphabetical)
- Every public class has a concise docstring
- Every feature must include unit tests
- Use Conventional Commits

## Order inside a class
I'd like every class to follow the same order.
```
class AudioSettings(BaseConfigurationModel):
    """Configuration for audio capture."""

    fields

    properties

    validators
```

## Fields order inside class
Logical grouping instead of alphabetical order

## Path, future reference
If multiple filesystem paths are added, extract a dedicated `PathResolver` component instead of expanding `ConfigurationLoader`.

## Implementation-driven development
Instead of asking "How should we design this?", we'll ask:
"Is this implementation the simplest one that satisfies our architecture?"

## Composition Root Rule
- Objects are created only in the composition root.
- Business classes never instantiate other business classes directly.
- Dependencies are passed through constructors.

This is one of the cleanest habits you can develop, and it will pay off enormously once we start wiring in Whisper, VAD, storage, and the API.

## For future subsystems, Definition of Done
- Architecture agreed
- ADR written (if needed)
- Public API designed
- Implementation complete
- Unit tests complete
- Integration tests (if applicable)
- Documentation updated
- Ruff passes
- MyPy passes
- Pytest passes
- Ready to merge
