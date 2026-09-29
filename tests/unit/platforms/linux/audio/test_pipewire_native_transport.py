from __future__ import annotations

import errno
import time
from concurrent.futures import (
    ThreadPoolExecutor,
)
from typing import Protocol, cast

from ats_pipewire_native._native import (  # type: ignore[import-untyped]
    ffi,
    lib,
)


class _TransportPointer(Protocol):
    def __getitem__(
        self,
        index: int,
    ) -> object: ...


def _create_transport(
    *,
    capacity: int,
    max_payload_size: int,
) -> object:
    transport_pointer = cast(
        _TransportPointer,
        ffi.new("ats_pw_transport **"),
    )
    error = ffi.new("ats_pw_error *")

    result = int(
        lib.ats_pw_transport_create(
            capacity,
            max_payload_size,
            transport_pointer,
            error,
        )
    )

    assert result == 0

    return transport_pointer[0]


def test_transport_round_trips_record_and_payload() -> None:
    transport = _create_transport(
        capacity=4,
        max_payload_size=32,
    )

    try:
        record = ffi.new("ats_pw_transport_record *")
        record.timestamp_ns = 123_456_789
        record.sample_rate = 48_000
        record.channels = 2
        record.sample_type = lib.ATS_PW_SAMPLE_TYPE_INT16
        record.frame_count = 3
        record.payload_size = 6

        payload = ffi.new(
            "unsigned char[]",
            b"abcdef",
        )

        assert (
            lib.ats_pw_transport_write(
                transport,
                record,
                payload,
            )
            == 0
        )

        out_record = ffi.new("ats_pw_transport_record *")
        out_payload = ffi.new(
            "unsigned char[]",
            32,
        )

        assert (
            lib.ats_pw_transport_read(
                transport,
                out_record,
                out_payload,
                32,
            )
            == lib.ATS_PW_TRANSPORT_READ_OK
        )

        assert out_record.timestamp_ns == 123_456_789
        assert out_record.sample_rate == 48_000
        assert out_record.channels == 2
        assert out_record.sample_type == lib.ATS_PW_SAMPLE_TYPE_INT16
        assert out_record.frame_count == 3
        assert out_record.payload_size == 6

        assert (
            bytes(
                ffi.buffer(
                    out_payload,
                    6,
                )
            )
            == b"abcdef"
        )

    finally:
        lib.ats_pw_transport_destroy(transport)


def test_empty_transport_returns_empty_status() -> None:
    transport = _create_transport(
        capacity=2,
        max_payload_size=8,
    )

    try:
        out_record = ffi.new("ats_pw_transport_record *")
        out_payload = ffi.new(
            "unsigned char[]",
            8,
        )

        assert (
            lib.ats_pw_transport_read(
                transport,
                out_record,
                out_payload,
                8,
            )
            == lib.ATS_PW_TRANSPORT_READ_EMPTY
        )

    finally:
        lib.ats_pw_transport_destroy(transport)


def test_full_transport_rejects_newest_record() -> None:
    transport = _create_transport(
        capacity=2,
        max_payload_size=8,
    )

    try:
        record = ffi.new("ats_pw_transport_record *")
        record.sample_rate = 48_000
        record.channels = 1
        record.sample_type = lib.ATS_PW_SAMPLE_TYPE_INT16
        record.frame_count = 1
        record.payload_size = 1

        first = ffi.new(
            "unsigned char[]",
            b"a",
        )
        second = ffi.new(
            "unsigned char[]",
            b"b",
        )
        third = ffi.new(
            "unsigned char[]",
            b"c",
        )

        assert (
            lib.ats_pw_transport_write(
                transport,
                record,
                first,
            )
            == 0
        )

        assert (
            lib.ats_pw_transport_write(
                transport,
                record,
                second,
            )
            == 0
        )

        assert (
            lib.ats_pw_transport_write(
                transport,
                record,
                third,
            )
            == -errno.EAGAIN
        )

        stats = ffi.new("ats_pw_transport_stats *")

        lib.ats_pw_transport_get_stats(
            transport,
            stats,
        )

        assert stats.written_records == 2
        assert stats.read_records == 0
        assert stats.dropped_records == 1
        assert stats.depth == 2

        out_record = ffi.new("ats_pw_transport_record *")
        out_payload = ffi.new(
            "unsigned char[]",
            8,
        )

        assert (
            lib.ats_pw_transport_read(
                transport,
                out_record,
                out_payload,
                8,
            )
            == lib.ATS_PW_TRANSPORT_READ_OK
        )
        assert out_payload[0] == ord("a")

        assert (
            lib.ats_pw_transport_read(
                transport,
                out_record,
                out_payload,
                8,
            )
            == lib.ATS_PW_TRANSPORT_READ_OK
        )
        assert out_payload[0] == ord("b")

    finally:
        lib.ats_pw_transport_destroy(transport)


def test_oversized_payload_is_rejected() -> None:
    transport = _create_transport(
        capacity=2,
        max_payload_size=4,
    )

    try:
        record = ffi.new("ats_pw_transport_record *")
        record.payload_size = 5

        payload = ffi.new(
            "unsigned char[]",
            b"abcde",
        )

        assert (
            lib.ats_pw_transport_write(
                transport,
                record,
                payload,
            )
            == -errno.EMSGSIZE
        )

        stats = ffi.new("ats_pw_transport_stats *")

        lib.ats_pw_transport_get_stats(
            transport,
            stats,
        )

        assert stats.depth == 0
        assert stats.dropped_records == 0

    finally:
        lib.ats_pw_transport_destroy(transport)


def test_small_read_buffer_does_not_consume_record() -> None:
    transport = _create_transport(
        capacity=2,
        max_payload_size=8,
    )

    try:
        record = ffi.new("ats_pw_transport_record *")
        record.payload_size = 4

        payload = ffi.new(
            "unsigned char[]",
            b"abcd",
        )

        assert (
            lib.ats_pw_transport_write(
                transport,
                record,
                payload,
            )
            == 0
        )

        out_record = ffi.new("ats_pw_transport_record *")
        small_buffer = ffi.new(
            "unsigned char[]",
            2,
        )

        assert (
            lib.ats_pw_transport_read(
                transport,
                out_record,
                small_buffer,
                2,
            )
            == -errno.ENOBUFS
        )

        stats = ffi.new("ats_pw_transport_stats *")

        lib.ats_pw_transport_get_stats(
            transport,
            stats,
        )

        assert stats.depth == 1

        correct_buffer = ffi.new(
            "unsigned char[]",
            8,
        )

        assert (
            lib.ats_pw_transport_read(
                transport,
                out_record,
                correct_buffer,
                8,
            )
            == lib.ATS_PW_TRANSPORT_READ_OK
        )

        assert (
            bytes(
                ffi.buffer(
                    correct_buffer,
                    4,
                )
            )
            == b"abcd"
        )

    finally:
        lib.ats_pw_transport_destroy(transport)


def test_transport_is_safe_between_one_producer_and_one_consumer() -> None:
    transport = _create_transport(
        capacity=8,
        max_payload_size=8,
    )

    record_count = 5_000

    def produce() -> None:
        record = ffi.new("ats_pw_transport_record *")
        record.sample_rate = 48_000
        record.channels = 1
        record.sample_type = lib.ATS_PW_SAMPLE_TYPE_INT16
        record.frame_count = 4
        record.payload_size = 8

        payload = ffi.new("uint64_t *")

        for sequence in range(record_count):
            record.timestamp_ns = sequence
            payload[0] = sequence

            while True:
                result = int(
                    lib.ats_pw_transport_write(
                        transport,
                        record,
                        payload,
                    )
                )

                if result == 0:
                    break

                assert result == -errno.EAGAIN

                time.sleep(0)

    def consume() -> list[int]:
        record = ffi.new("ats_pw_transport_record *")
        payload = ffi.new("uint64_t *")

        values: list[int] = []

        deadline = time.monotonic() + 10.0

        while len(values) < record_count:
            result = int(
                lib.ats_pw_transport_read(
                    transport,
                    record,
                    payload,
                    8,
                )
            )

            if result == lib.ATS_PW_TRANSPORT_READ_EMPTY:
                if time.monotonic() >= deadline:
                    raise AssertionError("Timed out waiting for native records")

                time.sleep(0)
                continue

            assert result == lib.ATS_PW_TRANSPORT_READ_OK

            values.append(int(payload[0]))

        return values

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            producer = executor.submit(produce)
            consumer = executor.submit(consume)

            producer.result(timeout=15)
            values = consumer.result(timeout=15)

        assert values == list(range(record_count))

        stats = ffi.new("ats_pw_transport_stats *")

        lib.ats_pw_transport_get_stats(
            transport,
            stats,
        )

        assert stats.written_records == record_count
        assert stats.read_records == record_count
        assert stats.depth == 0

    finally:
        lib.ats_pw_transport_destroy(transport)
