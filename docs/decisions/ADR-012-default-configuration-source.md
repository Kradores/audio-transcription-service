# ADR-011: Default Configuration Source

## Status
Accepted

## Decision
Application defaults live in `config/config.yaml`, not in Pydantic model definitions.

## Reason
Single source of truth, easier maintenance, avoids duplicated defaults.