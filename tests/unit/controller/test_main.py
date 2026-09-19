from unittest.mock import MagicMock, patch

from app.controller.main import main


@patch("app.controller.main.DevelopmentDistributionMetadataProvider")
@patch("app.controller.main.create_development_runtime_paths")
@patch("app.controller.main.multiprocessing.freeze_support")
@patch("app.controller.main.run_controller")
def test_main_runs_controller_with_development_distribution_metadata(
    run_controller: MagicMock,
    freeze_support: MagicMock,
    create_runtime_paths: MagicMock,
    create_distribution_metadata_provider: MagicMock,
) -> None:
    runtime_paths = MagicMock()
    distribution_metadata_provider = MagicMock()

    create_runtime_paths.return_value = runtime_paths
    create_distribution_metadata_provider.return_value = distribution_metadata_provider

    main()

    freeze_support.assert_called_once_with()
    create_runtime_paths.assert_called_once_with()
    create_distribution_metadata_provider.assert_called_once_with(
        project_root=runtime_paths.root_directory,
    )

    run_controller.assert_called_once_with(
        runtime_paths,
        distribution_metadata_provider=(distribution_metadata_provider),
    )
