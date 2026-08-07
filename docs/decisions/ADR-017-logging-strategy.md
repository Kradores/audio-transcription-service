# ADR-017: Logging Strategy

## Status

Accepted

## Context

The application needs reliable and observable logging throughout its lifecycle and
future subsystems.

Logging must:

- be configurable through the existing application configuration;
- provide meaningful information about application and subsystem behavior;
- support structured log output;
- avoid hidden global application state;
- remain easy to test;
- be available to all application layers without creating dependencies on
  higher-level packages.

The project already establishes that `app/core/` contains foundational
functionality and must not depend on higher-level application packages
(ADR-014).

The composition root is responsible for constructing long-lived application
dependencies, including logging (ADR-016).

No external logging library is currently required by the project.

## Decision

The application will use Python's standard-library `logging` package as its
logging implementation.

Logging configuration will be centralized in `app/core/logging.py`.

The logging subsystem will:

1. Configure the application's logging level from `LoggingSettings.level`.
2. Emit logs to the console by default.
3. Use a structured, consistent log format containing at least:
   - timestamp;
   - log level;
   - logger name;
   - message.
4. Configure logging once during application startup.
5. Be constructed and configured by the composition root.
6. Not be instantiated or configured by individual application components.
7. Avoid introducing a custom logger abstraction or Protocol. Components may
   obtain standard-library loggers by name after the logging system has been
   configured.
8. Remain independent of higher-level packages such as `app.audio`,
   `app.transcription`, `app.vad`, `app.storage`, and `app.api`.

No third-party logging dependency will be introduced unless a concrete future
requirement demonstrates that the standard-library implementation is
insufficient.

## Consequences

### Positive

- No additional runtime dependency is required.
- Logging configuration has a single owner.
- Logging behavior is consistent across the application.
- The logging subsystem remains independent of higher-level application
  components.
- Standard-library logging integrates naturally with Python libraries and
  frameworks.
- The implementation can be replaced or extended later without requiring
  application components to construct logging infrastructure themselves.

### Negative

- Python's standard logging API is less feature-rich than some third-party
  structured logging libraries.
- More advanced structured logging features may require custom formatters or
  handlers in the future.

These trade-offs are acceptable for the current application scope.

## Testing

The logging subsystem must have tests covering its observable behavior,
including:

- configured log level;
- configured handler/output;
- expected log record structure/format;
- repeated configuration not creating duplicate handlers.

The tests should avoid relying on global application state where practical and
should not require external logging services.

## Related Decisions

- ADR-014: Core packages must not depend on higher-level application packages.
- ADR-016: Application composition root.