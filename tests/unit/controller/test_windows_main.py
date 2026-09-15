from unittest.mock import MagicMock, patch

from app.controller.windows_main import main


@patch("app.controller.windows_main.create_installed_windows_runtime_paths")
@patch("app.controller.windows_main.multiprocessing.freeze_support")
@patch("app.controller.main.run_controller")
def test_main_runs_controller_with_installed_windows_paths(
    run_controller: MagicMock,
    freeze_support: MagicMock,
    create_runtime_paths: MagicMock,
) -> None:
    runtime_paths = MagicMock()
    create_runtime_paths.return_value = runtime_paths

    main()

    freeze_support.assert_called_once_with()
    create_runtime_paths.assert_called_once_with()
    run_controller.assert_called_once_with(
        runtime_paths,
    )
