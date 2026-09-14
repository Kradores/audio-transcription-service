from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from app.controller.runtime_process import (
    RuntimeProcessHost,
    RuntimeProcessSnapshot,
    RuntimeProcessState,
)
from app.controller.shell import ShellOpener
from app.controller.support_bundle import SupportBundleCreator, SupportBundleError
from app.core.runtime_paths import RuntimePaths

_REFRESH_INTERVAL_MS = 100


class ControllerWindow:
    """Minimal interactive host for the transcription runtime."""

    def __init__(
        self,
        *,
        root: tk.Tk,
        runtime_host: RuntimeProcessHost,
        runtime_paths: RuntimePaths,
        shell_opener: ShellOpener,
        support_bundle_creator: SupportBundleCreator,
    ) -> None:
        self._root = root
        self._runtime_host = runtime_host
        self._runtime_paths = runtime_paths
        self._shell_opener = shell_opener
        self._support_bundle_creator = support_bundle_creator
        self._closing = False

        self._status_value = tk.StringVar()

        self._include_transcript_database = tk.BooleanVar(
            value=False,
        )

        self._configure_window()
        self._create_widgets()
        self._apply_snapshot(
            runtime_host.snapshot,
        )

        self._root.protocol(
            "WM_DELETE_WINDOW",
            self._on_close,
        )

        self._schedule_refresh()

    def _configure_window(self) -> None:
        self._root.title(
            "Audio Transcription Service",
        )
        self._root.resizable(
            False,
            False,
        )

    def _create_widgets(self) -> None:
        frame = ttk.Frame(
            self._root,
            padding=20,
        )
        frame.grid()

        ttk.Label(
            frame,
            text="Audio Transcription Service",
        ).grid(
            row=0,
            column=0,
            columnspan=2,
            pady=(0, 16),
        )

        ttk.Label(
            frame,
            text="Status:",
        ).grid(
            row=1,
            column=0,
            sticky="w",
        )

        ttk.Label(
            frame,
            textvariable=self._status_value,
        ).grid(
            row=1,
            column=1,
            sticky="w",
        )

        self._start_button = ttk.Button(
            frame,
            text="Start",
            command=self._start,
        )
        self._start_button.grid(
            row=2,
            column=0,
            padx=(0, 8),
            pady=(16, 0),
        )

        self._stop_button = ttk.Button(
            frame,
            text="Stop",
            command=self._stop,
        )
        self._stop_button.grid(
            row=2,
            column=1,
            padx=(8, 0),
            pady=(16, 0),
        )

        ttk.Separator(
            frame,
            orient="horizontal",
        ).grid(
            row=3,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(16, 12),
        )

        ttk.Button(
            frame,
            text="Open Logs",
            command=self._open_logs,
        ).grid(
            row=4,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(0, 8),
        )

        ttk.Button(
            frame,
            text="Open Configuration",
            command=self._open_configuration,
        ).grid(
            row=5,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(0, 8),
        )

        ttk.Button(
            frame,
            text="Open Data Folder",
            command=self._open_data_folder,
        ).grid(
            row=6,
            column=0,
            columnspan=2,
            sticky="ew",
        )

        ttk.Separator(
            frame,
            orient="horizontal",
        ).grid(
            row=7,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(16, 12),
        )

        ttk.Checkbutton(
            frame,
            text=("Include transcript database (contains conversation text)"),
            variable=self._include_transcript_database,
        ).grid(
            row=8,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(0, 8),
        )

        ttk.Button(
            frame,
            text="Create Support Bundle",
            command=self._create_support_bundle,
        ).grid(
            row=9,
            column=0,
            columnspan=2,
            sticky="ew",
        )

    def _start(self) -> None:
        snapshot = self._runtime_host.start()
        self._apply_snapshot(snapshot)

    def _stop(self) -> None:
        snapshot = self._runtime_host.stop()
        self._apply_snapshot(snapshot)

    def _schedule_refresh(self) -> None:
        self._root.after(
            _REFRESH_INTERVAL_MS,
            self._refresh,
        )

    def _refresh(self) -> None:
        snapshot = self._runtime_host.refresh()
        self._apply_snapshot(snapshot)

        if self._closing and snapshot.state in {
            RuntimeProcessState.STOPPED,
            RuntimeProcessState.FAILED,
        }:
            self._root.destroy()
            return

        self._schedule_refresh()

    def _apply_snapshot(
        self,
        snapshot: RuntimeProcessSnapshot,
    ) -> None:
        self._status_value.set(
            self._status_text(snapshot),
        )

        active = snapshot.state in {
            RuntimeProcessState.STARTING,
            RuntimeProcessState.RUNNING,
            RuntimeProcessState.STOPPING,
        }

        self._start_button.configure(
            state="disabled" if active else "normal",
        )

        stoppable = snapshot.state in {
            RuntimeProcessState.STARTING,
            RuntimeProcessState.RUNNING,
        }

        self._stop_button.configure(
            state="normal" if stoppable else "disabled",
        )

    def _open_logs(self) -> None:
        self._run_shell_action(
            target_name="logs",
            action=lambda: self._shell_opener.open_directory(
                self._runtime_paths.logs_directory,
            ),
        )

    def _open_data_folder(self) -> None:
        self._run_shell_action(
            target_name="data folder",
            action=lambda: self._shell_opener.open_directory(
                self._runtime_paths.data_directory,
            ),
        )

    def _open_configuration(self) -> None:
        self._run_shell_action(
            target_name="configuration",
            action=lambda: self._shell_opener.open_text_file(
                self._runtime_paths.config_path,
            ),
        )

    def _run_shell_action(
        self,
        *,
        target_name: str,
        action: Callable[[], None],
    ) -> None:
        try:
            action()
        except OSError as exc:
            messagebox.showerror(
                "Audio Transcription Service",
                f"Could not open {target_name}.\n\n{exc}",
                parent=self._root,
            )

    def _create_support_bundle(self) -> None:
        include_database = self._include_transcript_database.get()

        try:
            result = self._support_bundle_creator.build(
                include_transcript_database=(include_database)
            )
        except (SupportBundleError, OSError) as exc:
            messagebox.showerror(
                "Audio Transcription Service",
                (f"Could not create support bundle.\n\n{exc}"),
                parent=self._root,
            )
            return

        # Privacy-safe default for the next bundle.
        self._include_transcript_database.set(False)

        warning_text = ""

        if result.warnings:
            warning_text = (
                f"\n\nWarnings: {len(result.warnings)}\nSee manifest.json inside the bundle."
            )

        database_text = "Included" if result.transcript_database_included else "Not included"

        messagebox.showinfo(
            "Audio Transcription Service",
            (
                "Support bundle created."
                f"\n\n{result.path.name}"
                f"\n\nTranscript database: {database_text}"
                f"{warning_text}"
            ),
            parent=self._root,
        )

        self._run_shell_action(
            target_name="support folder",
            action=lambda: self._shell_opener.open_directory(self._runtime_paths.support_directory),
        )

    @staticmethod
    def _status_text(
        snapshot: RuntimeProcessSnapshot,
    ) -> str:
        if snapshot.state is RuntimeProcessState.FAILED:
            if snapshot.failure_message:
                return f"Failed — {snapshot.failure_message}"

            return "Failed"

        return snapshot.state.value.capitalize()

    def _on_close(self) -> None:
        snapshot = self._runtime_host.refresh()

        if snapshot.state in {
            RuntimeProcessState.STARTING,
            RuntimeProcessState.RUNNING,
        }:
            self._closing = True

            snapshot = self._runtime_host.stop()
            self._apply_snapshot(snapshot)
            return

        if snapshot.state is RuntimeProcessState.STOPPING:
            self._closing = True
            return

        self._root.destroy()
