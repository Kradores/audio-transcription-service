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