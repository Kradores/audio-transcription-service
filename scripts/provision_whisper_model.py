from __future__ import annotations

import argparse
from pathlib import Path

from app.core.config.loader import ConfigurationLoader
from app.core.runtime_paths import create_development_runtime_paths
from app.models.whisper import LocalWhisperModelResolver
from app.models.whisper_provisioner import (
    HuggingFaceWhisperModelProvisioner,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Provision the configured Whisper model locally.",
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to the application configuration file.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    runtime_paths = create_development_runtime_paths(
        PROJECT_ROOT,
        config_path=args.config,
    )

    settings = ConfigurationLoader(runtime_paths).load()

    resolver = LocalWhisperModelResolver(
        runtime_paths.models_directory,
    )

    current = resolver.resolve(
        settings.whisper.model,
    )

    if current.ready:
        print(
            f"Whisper model '{settings.whisper.model.value}' is already ready at '{current.path}'."
        )
        return

    print(f"Provisioning Whisper model '{settings.whisper.model.value}'...")

    provisioner = HuggingFaceWhisperModelProvisioner(
        resolver=resolver,
    )

    result = provisioner.provision(
        settings.whisper.model,
    )

    print(f"Whisper model '{result.model.value}' is ready at '{result.path}'.")


if __name__ == "__main__":
    main()
