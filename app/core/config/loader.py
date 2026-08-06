from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.core.config.exceptions import (
    ConfigurationFileNotFoundError,
    ConfigurationParsingError,
    ConfigurationValidationError,
)
from app.core.config.models import Settings
from app.core.config.types import ConfigurationDocument


class ConfigurationLoader:
    """Loads and validates the application configuration."""

    def __init__(self, config_path: Path) -> None:
        if not config_path.suffix:
            raise ValueError("Configuration path must point to a file.")

        self._config_path = config_path.resolve()

    def load(self) -> Settings:
        """Load, validate and normalize the application configuration."""

        document = self._load_configuration_document()
        settings = self._create_settings(document)

        return self._resolve_relative_paths(settings)

    def _load_configuration_document(self) -> ConfigurationDocument:
        """Load the configuration document from disk."""

        try:
            with self._config_path.open("r", encoding="utf-8") as file:
                document = yaml.safe_load(file)

                if document is None:
                    raise ConfigurationParsingError(
                        f"Configuration file is empty: {self._config_path}"
                    )

        except FileNotFoundError as ex:
            raise ConfigurationFileNotFoundError(
                f"Configuration file not found: {self._config_path}"
            ) from ex

        except yaml.YAMLError as ex:
            raise ConfigurationParsingError(
                f"Failed to parse configuration file: {self._config_path}"
            ) from ex

        if not isinstance(document, dict):
            raise ConfigurationParsingError(
                f"Configuration file must contain a YAML mapping: {self._config_path}"
            )

        return document

    def _create_settings(self, document: ConfigurationDocument) -> Settings:
        """Create validated application settings."""

        try:
            return Settings.model_validate(document)

        except ValidationError as ex:
            raise ConfigurationValidationError(
                f"Invalid configuration in: {self._config_path}"
            ) from ex

    def _resolve_relative_paths(self, settings: Settings) -> Settings:
        """Resolve relative filesystem paths."""

        database_path = settings.database.path

        if database_path.is_absolute():
            return settings

        resolved_database = settings.database.model_copy(
            update={
                "path": (self._config_path.parent / database_path).resolve(),
            }
        )

        return settings.model_copy(
            update={
                "database": resolved_database,
            }
        )