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
✅ Configuration files
⬜ Application bootstrap
```

## Sprint 2 - Application Bootstrap Plan

| Order | Task                                                                             | Status     |
| ----: | -------------------------------------------------------------------------------- | ---------- |
|     1 | Populate `config/config.yaml`                                                    | Done       |
|     2 | Populate `config/config.example.yaml`                                            | Done       |
|     3 | Remove (or intentionally use) the unused configuration fixture files             | Done       |
|     4 | Implement the logging subsystem                                                  | Done       |
|     5 | Expand `Application` into the application lifecycle owner (`start()` / `stop()`) | Done       |
|     6 | Implement the composition root                                                   | Done       |
|     7 | Implement `main.py` and `__main__.py`                                            | PR-008     |
|     8 | Add startup integration tests                                                    | Validation |
|     9 | Verify `uv run python -m app` from a clean checkout                              | Sprint DoD |

### Why this order works
Each step builds on the previous one:
- Configuration provides valid input to the application.
- Logging gives visibility into startup and shutdown.
- Application defines the application's lifetime.
- Composition Root wires everything together in one place.
- Entry points (`main.py` / `__main__.py`) become very thin, which is exactly what ADR-016 intends.
- Integration tests verify the complete startup path rather than isolated pieces.
By the end of Sprint 2, the application should have a stable skeleton that future subsystems can plug into without revisiting the startup architecture.

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