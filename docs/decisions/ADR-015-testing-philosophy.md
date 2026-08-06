# ADR-015: Testing Philosophy

## Reason
Having a written architectural decision keeps the test suite consistent for years.

## Decision
Not about pytest.
Not about coverage.
About principles.

For example:
- Test behavior, not implementation.
- Prefer real filesystem over mocks where practical.
- One assertion of behavior per test.
- Tests should read like executable specifications.
- Mirror the production package structure.