# Roadmap
We have completed approximately this:
```
Sprint 1
────────────────────────────────────

✅ Project structure
✅ Python tooling
✅ Configuration models
✅ Configuration loader
✅ Tests
✅ Quality gates
⬜ Configuration files
⬜ Application bootstrap
```

## Sprint 2 - Application Bootstrap

Our objective is not to transcribe audio.

Our objective is:
- Start the application successfully.

Everything else builds on that.
I'd break it into four small PRs.
```
PR-006
Application object

PR-007
Composition root

PR-008
Startup

PR-009
Logging
```
Each PR should remain independently reviewable.

## My expectation for the end of Sprint 2

When Sprint 2 finishes, I want the project to feel like a real application.
```
uv run python -m app
```
should:
- load configuration,
- construct the application,
- report successful startup,
- exit cleanly,
- and leave the quality pipeline completely green.

Once we reach that point, we can start on the part everyone is excited about—designing the audio capture pipeline. The difference is that we'll be building it on a foundation that's already proven itself.