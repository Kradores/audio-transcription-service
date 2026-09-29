from __future__ import annotations

from cffi import FFI  # type: ignore[import-untyped]

NATIVE_SOURCE_DIR = "src/ats_pipewire_native/csrc"

ffibuilder = FFI()

ffibuilder.cdef(
    """
    typedef struct ats_pw_client ats_pw_client;

    typedef struct ats_pw_error {
        int code;
        char message[256];
    } ats_pw_error;

    const char *ats_pw_headers_version(void);
    const char *ats_pw_library_version(void);

    int ats_pw_client_create(
        ats_pw_client **out_client,
        ats_pw_error *error
    );

    int ats_pw_client_start(
        ats_pw_client *client,
        ats_pw_error *error
    );

    int ats_pw_client_stop(
        ats_pw_client *client,
        ats_pw_error *error
    );

    void ats_pw_client_destroy(
        ats_pw_client *client
    );

    int ats_pw_client_is_started(
        const ats_pw_client *client
    );

    typedef struct ats_pw_transport ats_pw_transport;

    typedef enum ats_pw_sample_type {
        ATS_PW_SAMPLE_TYPE_INT16 = 1,
        ATS_PW_SAMPLE_TYPE_FLOAT32 = 2
    } ats_pw_sample_type;

    typedef struct ats_pw_transport_record {
        uint64_t timestamp_ns;
        uint32_t sample_rate;
        uint32_t channels;
        uint32_t sample_type;
        uint32_t frame_count;
        uint32_t payload_size;
    } ats_pw_transport_record;

    typedef struct ats_pw_transport_stats {
        uint64_t written_records;
        uint64_t read_records;
        uint64_t dropped_records;
        uint32_t depth;
        uint32_t capacity;
        uint32_t max_payload_size;
    } ats_pw_transport_stats;

    enum {
        ATS_PW_TRANSPORT_READ_EMPTY = 0,
        ATS_PW_TRANSPORT_READ_OK = 1
    };

    int ats_pw_transport_create(
        uint32_t capacity,
        uint32_t max_payload_size,
        ats_pw_transport **out_transport,
        ats_pw_error *error
    );

    void ats_pw_transport_destroy(
        ats_pw_transport *transport
    );

    int ats_pw_transport_write(
        ats_pw_transport *transport,
        const ats_pw_transport_record *record,
        const void *payload
    );

    int ats_pw_transport_read(
        ats_pw_transport *transport,
        ats_pw_transport_record *out_record,
        void *out_payload,
        uint32_t out_payload_capacity
    );

    void ats_pw_transport_get_stats(
        const ats_pw_transport *transport,
        ats_pw_transport_stats *out_stats
    );

    typedef struct ats_pw_capture ats_pw_capture;

    typedef enum ats_pw_capture_state {
        ATS_PW_CAPTURE_STATE_ERROR = -1,
        ATS_PW_CAPTURE_STATE_UNCONNECTED = 0,
        ATS_PW_CAPTURE_STATE_CONNECTING = 1,
        ATS_PW_CAPTURE_STATE_PAUSED = 2,
        ATS_PW_CAPTURE_STATE_STREAMING = 3
    } ats_pw_capture_state;

    typedef struct ats_pw_capture_stats {
        int32_t stream_state;

        uint32_t sample_rate;
        uint32_t channels;
        uint32_t sample_type;

        uint64_t process_callbacks;
        uint64_t invalid_buffers;
        uint64_t oversized_buffers;

        ats_pw_transport_stats transport;
    } ats_pw_capture_stats;

    int ats_pw_microphone_create(
        ats_pw_client *client,
        uint32_t queue_capacity,
        uint32_t max_payload_size,
        ats_pw_capture **out_capture,
        ats_pw_error *error
    );

    int ats_pw_capture_start(
        ats_pw_capture *capture,
        ats_pw_error *error
    );

    int ats_pw_capture_stop(
        ats_pw_capture *capture,
        ats_pw_error *error
    );

    void ats_pw_capture_destroy(
        ats_pw_capture *capture
    );

    int ats_pw_capture_read(
        ats_pw_capture *capture,
        ats_pw_transport_record *out_record,
        void *out_payload,
        uint32_t out_payload_capacity
    );

    void ats_pw_capture_get_stats(
        const ats_pw_capture *capture,
        ats_pw_capture_stats *out_stats
    );

    typedef struct ats_pw_source_info {
        int available;
        char node_name[256];
    } ats_pw_source_info;

    int ats_pw_client_get_default_source(
        ats_pw_client *client,
        ats_pw_source_info *out_source
    );
    """
)

ffibuilder.set_source_pkgconfig(
    "ats_pipewire_native._native",
    ["libpipewire-0.3"],
    """
    #include "ats_pipewire.h"
    """,
    sources=[
        f"{NATIVE_SOURCE_DIR}/ats_pipewire.c",
    ],
    depends=[
        f"{NATIVE_SOURCE_DIR}/ats_pipewire.h",
    ],
    include_dirs=[
        NATIVE_SOURCE_DIR,
    ],
)
