from __future__ import annotations

import errno
from typing import Protocol, cast

from ats_pipewire_native._native import (  # type: ignore[import-untyped]
    ffi,
    lib,
)


class _Pointer(Protocol):
    def __getitem__(
        self,
        index: int,
    ) -> object: ...


def test_microphone_capture_requires_started_client() -> None:
    client_pointer = cast(
        _Pointer,
        ffi.new("ats_pw_client **"),
    )

    capture_pointer = cast(
        _Pointer,
        ffi.new("ats_pw_capture **"),
    )

    error = ffi.new("ats_pw_error *")

    assert (
        lib.ats_pw_client_create(
            client_pointer,
            error,
        )
        == 0
    )

    client = client_pointer[0]

    try:
        assert (
            lib.ats_pw_microphone_create(
                client,
                4,
                65_536,
                capture_pointer,
                error,
            )
            == 0
        )

        capture = capture_pointer[0]

        try:
            result = int(
                lib.ats_pw_capture_start(
                    capture,
                    error,
                )
            )

            assert result == -errno.ENOTCONN

            record = ffi.new("ats_pw_transport_record *")

            payload = ffi.new(
                "unsigned char[]",
                65_536,
            )

            assert (
                lib.ats_pw_capture_read(
                    capture,
                    record,
                    payload,
                    65_536,
                )
                == lib.ATS_PW_TRANSPORT_READ_EMPTY
            )

        finally:
            lib.ats_pw_capture_destroy(capture)

    finally:
        lib.ats_pw_client_destroy(client)
