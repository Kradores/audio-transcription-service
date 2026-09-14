from __future__ import annotations

import yaml
from pydantic import ValidationError

from app.core.config.exceptions import (
    ConfigurationFileNotFoundError,
    ConfigurationParsingError,
    ConfigurationValidationError,
)
from app.core.config.models import Settings
from app.core.config.types import ConfigurationDocument
from app.core.runtime_paths import RuntimePaths


class ConfigurationLoader:
    """Loads and validates the application configuration."""

    def __init__(self, runtime_paths: RuntimePaths) -> None:
        if not runtime_paths.config_path.suffix:
            raise ValueError("Configuration path must point to a file.")

        self._runtime_paths = runtime_paths
        self._config_path = runtime_paths.config_path

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
        """Resolve configured filesystem paths against the runtime root."""

        database_path = self._runtime_paths.resolve(
            settings.database.path,
        )
        logging_path = self._runtime_paths.resolve(
            settings.logging.file.path,
        )
        capture_directory = self._runtime_paths.resolve(
            settings.whisper.slow_inference_capture.directory,
        )

        resolved_database = settings.database.model_copy(
            update={
                "path": database_path,
            }
        )

        resolved_log_file = settings.logging.file.model_copy(
            update={
                "path": logging_path,
            }
        )
        resolved_logging = settings.logging.model_copy(
            update={
                "file": resolved_log_file,
            }
        )

        resolved_slow_capture = settings.whisper.slow_inference_capture.model_copy(
            update={
                "directory": capture_directory,
            }
        )
        resolved_whisper = settings.whisper.model_copy(
            update={
                "slow_inference_capture": resolved_slow_capture,
            }
        )

        return settings.model_copy(
            update={
                "database": resolved_database,
                "logging": resolved_logging,
                "whisper": resolved_whisper,
            }
        )
