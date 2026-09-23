from pathlib import Path

import pytest
from pytest import MonkeyPatch

from app.core.runtime_paths import (
    APPLICATION_DATA_DIRECTORY_NAME,
    create_development_runtime_paths,
    create_installed_windows_runtime_paths,
)


def test_development_runtime_paths_use_project_root(
    tmp_path: Path,
) -> None:
    paths = create_development_runtime_paths(tmp_path)

    assert paths.root_directory == tmp_path.resolve()
    assert paths.config_path == (tmp_path / "config" / "config.yaml").resolve()
    assert paths.data_directory == (tmp_path / "data").resolve()
    assert paths.logs_directory == (tmp_path / "logs").resolve()
    assert paths.diagnostics_directory == (tmp_path / "diagnostics").resolve()
    assert paths.models_directory == (tmp_path / "models").resolve()
    assert paths.support_directory == (tmp_path / "support").resolve()


def test_default_development_runtime_paths_ignore_current_working_directory(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    expected = create_development_runtime_paths()
    other_directory = tmp_path / "other"
    other_directory.mkdir()

    monkeypatch.chdir(other_directory)

    assert create_development_runtime_paths() == expected


def test_development_runtime_paths_resolve_relative_config_against_project_root(
    tmp_path: Path,
) -> None:
    paths = create_development_runtime_paths(
        tmp_path,
        config_path=Path("custom/settings.yaml"),
    )

    assert paths.config_path == (tmp_path / "custom" / "settings.yaml").resolve()


def test_runtime_paths_resolve_relative_path_against_runtime_root(
    tmp_path: Path,
) -> None:
    paths = create_development_runtime_paths(tmp_path)

    assert (
        paths.resolve(Path("data/transcripts.db"))
        == (tmp_path / "data" / "transcripts.db").resolve()
    )


def test_runtime_paths_preserve_absolute_path(
    tmp_path: Path,
) -> None:
    paths = create_development_runtime_paths(tmp_path)
    absolute_path = (tmp_path / "outside" / "transcripts.db").resolve()

    assert paths.resolve(absolute_path) == absolute_path


def test_installed_windows_runtime_paths_use_local_app_data(
    tmp_path: Path,
) -> None:
    paths = create_installed_windows_runtime_paths(tmp_path)
    root = (tmp_path / APPLICATION_DATA_DIRECTORY_NAME).resolve()

    assert paths.root_directory == root
    assert paths.config_path == root / "config" / "config.yaml"
    assert paths.data_directory == root / "data"
    assert paths.logs_directory == root / "logs"
    assert paths.diagnostics_directory == root / "diagnostics"
    assert paths.models_directory == root / "models"
    assert paths.support_directory == root / "support"


def test_installed_windows_runtime_paths_read_local_app_data(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    paths = create_installed_windows_runtime_paths()

    assert paths.root_directory == (tmp_path / APPLICATION_DATA_DIRECTORY_NAME).resolve()


def test_installed_windows_runtime_paths_require_local_app_data(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    with pytest.raises(
        RuntimeError,
        match="LOCALAPPDATA is required",
    ):
        create_installed_windows_runtime_paths()
