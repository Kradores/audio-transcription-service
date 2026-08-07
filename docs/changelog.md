## Configuration Subsystem

- Introduced immutable typed configuration models using Pydantic.
- Added YAML configuration loader with custom exceptions.
- Added comprehensive unit tests covering happy paths, validation, boundary values, immutability, and nested models.
- Established reusable testing infrastructure with builders and fixtures.
- Configured Ruff, MyPy, Pytest, and editable package installation.

## Configuration milestone

We now have:
- `config/config.yaml` populated
- `config/config.example.yaml` populated
- Empty unused fixture directory removed
- Real default configuration tested through `ConfigurationLoader`
- Existing configuration unit tests still passing
- Path typing expectations corrected
- `pytest` — 37/37 passed
- `ruff check .` — passed
- `mypy .` — passed


## Sprint 2 status

We have successfully completed:

1. Configuration
    - Production config/config.yaml
    - config/config.example.yaml
    - Removed unused fixtures
    - Default configuration integration test
    - 37 tests passing
    - Ruff + mypy green

2. Logging
    - ADR-017 accepted
    - app/core/logging.py
    - Standard-library logging
    - Configurable log level
    - Console output
    - Consistent structured format
    - No duplicate handlers
    - 4 dedicated logging tests
    - Full quality gate green