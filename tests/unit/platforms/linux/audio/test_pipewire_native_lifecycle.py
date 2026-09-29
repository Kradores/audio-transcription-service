from __future__ import annotations

import errno
from typing import Protocol

import pytest
from ats_pipewire_native._native import ffi, lib  # type: ignore[import-untyped]


class _NativeError(Protocol):
    message: object


def _error_message(
    error: _NativeError,
) -> str:
    return str(
        ffi.string(
            error.message,
        ).decode()
    )


def _create_client() -> object:
    client_ptr = ffi.new("ats_pw_client **")
    error = ffi.new("ats_pw_error *")

    result = lib.ats_pw_client_create(
        client_ptr,
        error,
    )

    assert result == 0, _error_message(error)
    assert client_ptr[0] != ffi.NULL

    return client_ptr[0]


def test_client_can_be_created_and_destroyed_repeatedly() -> None:
    for _ in range(10):
        client = _create_client()

        assert lib.ats_pw_client_is_started(client) == 0

        lib.ats_pw_client_destroy(client)


def test_stop_before_start_is_idempotent() -> None:
    client = _create_client()

    try:
        error = ffi.new("ats_pw_error *")

        first_result = lib.ats_pw_client_stop(
            client,
            error,
        )
        second_result = lib.ats_pw_client_stop(
            client,
            error,
        )

        assert first_result == 0
        assert second_result == 0
        assert lib.ats_pw_client_is_started(client) == 0

    finally:
        lib.ats_pw_client_destroy(client)


def test_destroy_accepts_null() -> None:
    lib.ats_pw_client_destroy(ffi.NULL)


def test_start_reports_unavailable_server_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "PIPEWIRE_REMOTE",
        "ats-pipewire-test-server-that-does-not-exist",
    )

    client = _create_client()

    try:
        error = ffi.new("ats_pw_error *")

        result = lib.ats_pw_client_start(
            client,
            error,
        )

        assert result < 0
        assert error.code != 0
        assert _error_message(error)
        assert lib.ats_pw_client_is_started(client) == 0

        # A failed start must still leave the client safe to stop.
        assert (
            lib.ats_pw_client_stop(
                client,
                error,
            )
            == 0
        )

    finally:
        lib.ats_pw_client_destroy(client)


def test_default_source_is_unavailable_before_start() -> None:
    client_ptr = ffi.new("ats_pw_client **")
    error = ffi.new("ats_pw_error *")
    source = ffi.new("ats_pw_source_info *")

    assert (
        lib.ats_pw_client_create(
            client_ptr,
            error,
        )
        == 0
    )

    client = client_ptr[0]

    try:
        assert (
            lib.ats_pw_client_get_default_source(
                client,
                source,
            )
            == 0
        )

        assert source.available == 0
        assert ffi.string(source.node_name) == b""

    finally:
        lib.ats_pw_client_destroy(client)


def test_default_source_rejects_invalid_arguments() -> None:
    source = ffi.new("ats_pw_source_info *")

    assert (
        lib.ats_pw_client_get_default_source(
            ffi.NULL,
            source,
        )
        == -errno.EINVAL
    )
