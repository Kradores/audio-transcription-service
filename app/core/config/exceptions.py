from __future__ import annotations


class ConfigurationError(Exception):
    """Base class for configuration-related errors."""


class ConfigurationFileNotFoundError(ConfigurationError):
    """Raised when the configuration file cannot be found."""


class ConfigurationParsingError(ConfigurationError):
    """Raised when the configuration file cannot be parsed."""


class ConfigurationValidationError(ConfigurationError):
    """Raised when configuration validation fails."""
