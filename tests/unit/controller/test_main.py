from pathlib import Path
from unittest.mock import MagicMock, call, patch

from app.controller.main import (
    main,
    run_controller,
)


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


@patch("app.controller.main.ControllerWindow")
@patch("app.controller.main.SupportBundleBuilder")
@patch("app.controller.main.WindowsShellOpener")
@patch("app.controller.main.WhisperModelProvisioningHost")
@patch("app.controller.main.ConfiguredWhisperModelStatusProvider")
@patch("app.controller.main.LocalWhisperModelResolver")
@patch("app.controller.main.RuntimeProcessHost")
@patch("app.controller.main.tk.Tk")
@patch("app.controller.main.configure_controller_logging")
@patch("app.controller.main.ConfigurationLoader")
def test_run_controller_configures_logging_before_controller_components(
    configuration_loader: MagicMock,
    configure_controller_logging: MagicMock,
    create_tk: MagicMock,
    create_runtime_host: MagicMock,
    create_model_resolver: MagicMock,
    create_status_provider: MagicMock,
    create_provisioning_host: MagicMock,
    create_shell_opener: MagicMock,
    create_support_bundle: MagicMock,
    create_window: MagicMock,
) -> None:
    del (
        create_runtime_host,
        create_model_resolver,
        create_status_provider,
        create_provisioning_host,
        create_shell_opener,
        create_support_bundle,
        create_window,
    )

    runtime_paths = MagicMock()

    settings = MagicMock()
    configuration_loader.return_value.load.return_value = settings

    configure_controller_logging.return_value = Path(
        "logs/audio-transcription-service.controller.log"
    )

    parent = MagicMock()

    parent.attach_mock(
        configure_controller_logging,
        "logging",
    )
    parent.attach_mock(
        create_tk,
        "tk",
    )

    root = create_tk.return_value

    run_controller(runtime_paths)

    assert parent.mock_calls[:2] == [
        call.logging(settings.logging),
        call.tk(),
    ]

    root.mainloop.assert_called_once_with()
