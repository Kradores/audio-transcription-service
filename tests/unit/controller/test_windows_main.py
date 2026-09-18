from unittest.mock import MagicMock, patch

from app.controller.windows_main import main


@patch("app.controller.windows_main.FileDistributionMetadataProvider")
@patch("app.controller.windows_main.get_packaged_distribution_metadata_path")
@patch("app.controller.windows_main.create_installed_windows_runtime_paths")
@patch("app.controller.windows_main.multiprocessing.freeze_support")
@patch("app.controller.main.run_controller")
def test_main_runs_controller_with_installed_windows_metadata(
    run_controller: MagicMock,
    freeze_support: MagicMock,
    create_runtime_paths: MagicMock,
    get_distribution_metadata_path: MagicMock,
    create_distribution_metadata_provider: MagicMock,
) -> None:
    runtime_paths = MagicMock()
    metadata_path = MagicMock()
    metadata_provider = MagicMock()

    create_runtime_paths.return_value = runtime_paths
    get_distribution_metadata_path.return_value = metadata_path
    create_distribution_metadata_provider.return_value = metadata_provider

    main()

    freeze_support.assert_called_once_with()
    create_runtime_paths.assert_called_once_with()
    get_distribution_metadata_path.assert_called_once_with()

    create_distribution_metadata_provider.assert_called_once_with(
        metadata_path,
    )

    run_controller.assert_called_once_with(
        runtime_paths,
        distribution_metadata_provider=metadata_provider,
    )
