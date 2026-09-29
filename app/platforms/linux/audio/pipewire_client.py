from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast


class PipeWireClient(Protocol):
    """Own one native PipeWire client lifecycle."""

    @property
    def is_started(self) -> bool:
        """Return whether the native client is connected and started."""

    def start(self) -> None:
        """Start the native client."""

    def stop(self) -> None:
        """Stop the native client."""

    def close(self) -> None:
        """Destroy native resources."""


class PipeWireClientFactory(Protocol):
    def create(self) -> PipeWireClient:
        """Create one fresh PipeWire client."""


class PipeWireClientError(RuntimeError):
    """Raised when the native PipeWire client reports an error."""

    def __init__(
        self,
        *,
        operation: str,
        code: int,
        message: str,
    ) -> None:
        self.operation = operation
        self.code = code

        detail = message or (f"{operation} failed with native error code {code}.")

        super().__init__(detail)


class _CffiClientPointer(Protocol):
    def __getitem__(
        self,
        index: int,
    ) -> object: ...


class _CffiErrorPointer(Protocol):
    code: int
    message: object


class _CffiApi(Protocol):
    NULL: object

    def new(
        self,
        cdecl: str,
    ) -> object: ...

    def string(
        self,
        cdata: object,
    ) -> bytes: ...


class _NativeLibrary(Protocol):
    def ats_pw_client_create(
        self,
        out_client: object,
        error: object,
    ) -> int: ...

    def ats_pw_client_start(
        self,
        client: object,
        error: object,
    ) -> int: ...

    def ats_pw_client_stop(
        self,
        client: object,
        error: object,
    ) -> int: ...

    def ats_pw_client_destroy(
        self,
        client: object,
    ) -> None: ...

    def ats_pw_client_is_started(
        self,
        client: object,
    ) -> int: ...


@dataclass(frozen=True, slots=True)
class _NativeBindings:
    ffi: _CffiApi
    lib: _NativeLibrary


type NativeBindingsLoader = Callable[
    [],
    _NativeBindings,
]


def _load_native_bindings() -> _NativeBindings:
    from ats_pipewire_native._native import (  # type: ignore[import-untyped]
        ffi,
        lib,
    )

    return _NativeBindings(
        ffi=cast(_CffiApi, ffi),
        lib=cast(_NativeLibrary, lib),
    )


class CffiPipeWireClient:
    """Typed owner around one CFFI PipeWire client handle."""

    def __init__(
        self,
        *,
        ffi: _CffiApi,
        lib: _NativeLibrary,
    ) -> None:
        self._ffi = ffi
        self._lib = lib
        self._closed = False

        client_pointer = cast(
            _CffiClientPointer,
            ffi.new("ats_pw_client **"),
        )
        error = self._new_error()

        result = lib.ats_pw_client_create(
            client_pointer,
            error,
        )

        self._raise_for_result(
            operation="Create PipeWire client",
            result=result,
            error=error,
        )

        client = client_pointer[0]

        if client == ffi.NULL:
            raise PipeWireClientError(
                operation="Create PipeWire client",
                code=0,
                message=("Create PipeWire client returned no native client handle."),
            )

        self._client = client

    @property
    def is_started(self) -> bool:
        if self._closed:
            return False

        return bool(
            self._lib.ats_pw_client_is_started(
                self._client,
            )
        )

    def start(self) -> None:
        self._require_open()

        error = self._new_error()

        result = self._lib.ats_pw_client_start(
            self._client,
            error,
        )

        self._raise_for_result(
            operation="Start PipeWire client",
            result=result,
            error=error,
        )

    def stop(self) -> None:
        if self._closed:
            return

        error = self._new_error()

        result = self._lib.ats_pw_client_stop(
            self._client,
            error,
        )

        self._raise_for_result(
            operation="Stop PipeWire client",
            result=result,
            error=error,
        )

    def close(self) -> None:
        if self._closed:
            return

        self._lib.ats_pw_client_destroy(
            self._client,
        )

        self._client = self._ffi.NULL
        self._closed = True

    def _new_error(
        self,
    ) -> _CffiErrorPointer:
        return cast(
            _CffiErrorPointer,
            self._ffi.new("ats_pw_error *"),
        )

    def _raise_for_result(
        self,
        *,
        operation: str,
        result: int,
        error: _CffiErrorPointer,
    ) -> None:
        if result >= 0:
            return

        code = error.code or -result

        message = self._ffi.string(
            error.message,
        ).decode(
            errors="replace",
        )

        raise PipeWireClientError(
            operation=operation,
            code=code,
            message=message,
        )

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("PipeWire client is already closed.")


class CffiPipeWireClientFactory:
    def __init__(
        self,
        *,
        bindings_loader: NativeBindingsLoader = (_load_native_bindings),
    ) -> None:
        self._bindings_loader = bindings_loader

    def create(self) -> PipeWireClient:
        bindings = self._bindings_loader()

        return CffiPipeWireClient(
            ffi=bindings.ffi,
            lib=bindings.lib,
        )
