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
- I tell you whether:
    1. 🟢 No ADR needed — implementation detail.
    2. 📘 ADR recommended — architectural decision.
- If needed, you create/update the ADR.
- We implement.
- We test.
- We update the relevant documentation (if needed).
- We commit.