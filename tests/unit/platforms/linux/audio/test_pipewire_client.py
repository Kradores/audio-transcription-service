from __future__ import annotations

import pytest

from app.platforms.linux.audio.pipewire_client import (
    CffiPipeWireClient,
    PipeWireClientError,
)


class FakeClientPointer:
    def __init__(self) -> None:
        self.value: object | None = None

    def __getitem__(
        self,
        index: int,
    ) -> object | None:
        assert index == 0
        return self.value


class FakeError:
    def __init__(self) -> None:
        self.code = 0
        self.message: object = b""


class FakeFfi:
    NULL: object = None

    def new(
        self,
        cdecl: str,
    ) -> object:
        if cdecl == "ats_pw_client **":
            return FakeClientPointer()

        if cdecl == "ats_pw_error *":
            return FakeError()

        raise AssertionError(f"Unexpected C declaration: {cdecl}")

    def string(
        self,
        cdata: object,
    ) -> bytes:
        assert isinstance(cdata, bytes)
        return cdata


class FakeNativeLibrary:
    def __init__(self) -> None:
        self.handle = object()

        self.create_result = 0
        self.start_result = 0
        self.stop_result = 0

        self.error_code = 0
        self.error_message = b""

        self.started = False

        self.create_calls = 0
        self.start_calls = 0
        self.stop_calls = 0
        self.destroy_calls = 0

    def ats_pw_client_create(
        self,
        out_client: object,
        error: object,
    ) -> int:
        self.create_calls += 1

        assert isinstance(
            out_client,
            FakeClientPointer,
        )
        assert isinstance(
            error,
            FakeError,
        )

        if self.create_result < 0:
            self._set_error(error)
            return self.create_result

        out_client.value = self.handle

        return 0

    def ats_pw_client_start(
        self,
        client: object,
        error: object,
    ) -> int:
        self.start_calls += 1

        assert client is self.handle
        assert isinstance(error, FakeError)

        if self.start_result < 0:
            self._set_error(error)
            return self.start_result

        self.started = True

        return 0

    def ats_pw_client_stop(
        self,
        client: object,
        error: object,
    ) -> int:
        self.stop_calls += 1

        assert client is self.handle
        assert isinstance(error, FakeError)

        if self.stop_result < 0:
            self._set_error(error)
            return self.stop_result

        self.started = False

        return 0

    def ats_pw_client_destroy(
        self,
        client: object,
    ) -> None:
        assert client is self.handle

        self.destroy_calls += 1
        self.started = False

    def ats_pw_client_is_started(
        self,
        client: object,
    ) -> int:
        assert client is self.handle

        return int(self.started)

    def _set_error(
        self,
        error: FakeError,
    ) -> None:
        error.code = self.error_code
        error.message = self.error_message


def create_client(
    library: FakeNativeLibrary,
) -> CffiPipeWireClient:
    return CffiPipeWireClient(
        ffi=FakeFfi(),
        lib=library,
    )


def test_client_owns_native_lifecycle() -> None:
    library = FakeNativeLibrary()
    client = create_client(library)

    assert library.create_calls == 1
    assert not client.is_started

    client.start()

    assert client.is_started
    assert library.start_calls == 1

    client.stop()

    assert not client.is_started
    assert library.stop_calls == 1

    client.close()

    assert not client.is_started
    assert library.destroy_calls == 1


def test_close_is_idempotent() -> None:
    library = FakeNativeLibrary()
    client = create_client(library)

    client.close()
    client.close()

    assert library.destroy_calls == 1


def test_stop_after_close_is_safe() -> None:
    library = FakeNativeLibrary()
    client = create_client(library)

    client.close()
    client.stop()

    assert library.stop_calls == 0


def test_start_after_close_is_rejected() -> None:
    client = create_client(
        FakeNativeLibrary(),
    )

    client.close()

    with pytest.raises(
        RuntimeError,
        match="already closed",
    ):
        client.start()


def test_create_error_is_translated() -> None:
    library = FakeNativeLibrary()
    library.create_result = -12
    library.error_code = 12
    library.error_message = b"Allocation failed"

    with pytest.raises(
        PipeWireClientError,
        match="Allocation failed",
    ) as error:
        create_client(library)

    assert error.value.operation == ("Create PipeWire client")
    assert error.value.code == 12


def test_start_error_is_translated() -> None:
    library = FakeNativeLibrary()
    library.start_result = -112
    library.error_code = 112
    library.error_message = b"Connect to PipeWire server: Host is down"

    client = create_client(library)

    try:
        with pytest.raises(
            PipeWireClientError,
            match="Host is down",
        ) as error:
            client.start()

        assert error.value.code == 112
        assert not client.is_started

    finally:
        client.close()


def test_stop_error_is_translated() -> None:
    library = FakeNativeLibrary()
    client = create_client(library)

    client.start()

    library.stop_result = -5
    library.error_code = 5
    library.error_message = b"Disconnect from PipeWire server: I/O error"

    try:
        with pytest.raises(
            PipeWireClientError,
            match="I/O error",
        ) as error:
            client.stop()

        assert error.value.code == 5

    finally:
        client.close()
