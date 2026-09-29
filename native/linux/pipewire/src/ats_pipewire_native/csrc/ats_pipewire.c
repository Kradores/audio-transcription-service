#include "ats_pipewire.h"

#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdatomic.h>
#include <stdint.h>
#include <string.h>
#include <time.h>

#include <pipewire/pipewire.h>
#include <spa/utils/result.h>
#include <spa/param/audio/format-utils.h>
#include <pipewire/extensions/metadata.h>
#include <spa/utils/json.h>


#define ATS_PW_NODE_NAME_CAPACITY 256
#define ATS_PW_MEDIA_CLASS_CAPACITY 64
#define ATS_PW_OBSERVER_SYNC_TIMEOUT_NS 5000000000LL

typedef struct ats_pw_observed_node {
    uint32_t id;

    char node_name[
        ATS_PW_NODE_NAME_CAPACITY
    ];

    char media_class[
        ATS_PW_MEDIA_CLASS_CAPACITY
    ];

    struct ats_pw_observed_node *next;
} ats_pw_observed_node;


struct ats_pw_client {
    struct pw_thread_loop *thread_loop;
    struct pw_context *context;
    struct pw_core *core;

    struct spa_hook core_listener;
    bool core_listener_added;

    struct pw_registry *registry;
    struct spa_hook registry_listener;

    struct pw_metadata *default_metadata;
    struct spa_hook metadata_listener;
    uint32_t default_metadata_id;

    ats_pw_observed_node *nodes;

    char default_source_name[
        ATS_PW_NODE_NAME_CAPACITY
    ];

    int observer_sync_seq;
    bool observer_sync_pending;

    bool pipewire_initialized;
    bool loop_started;
    bool started;
    bool registry_listener_added;
};


struct ats_pw_transport {
    uint32_t capacity;
    uint32_t max_payload_size;

    ats_pw_transport_record *records;
    unsigned char *payloads;

    _Atomic uint64_t write_sequence;
    _Atomic uint64_t read_sequence;
    _Atomic uint64_t dropped_records;
};


struct ats_pw_capture {
    ats_pw_client *client;

    struct pw_stream *stream;
    struct spa_hook stream_listener;

    ats_pw_transport *transport;

    _Atomic int stream_state;
    _Atomic uint32_t sample_rate;
    _Atomic uint32_t channels;
    _Atomic uint32_t sample_type;

    _Atomic uint64_t process_callbacks;
    _Atomic uint64_t invalid_buffers;
    _Atomic uint64_t oversized_buffers;

    bool listener_added;
    bool ever_started;
};


static void ats_pw_capture_on_state_changed(
    void *userdata,
    enum pw_stream_state old_state,
    enum pw_stream_state state,
    const char *error
);

static void ats_pw_capture_on_param_changed(
    void *userdata,
    uint32_t id,
    const struct spa_pod *param
);

static void ats_pw_capture_on_process(
    void *userdata
);


static void ats_pw_client_on_registry_global(
    void *userdata,
    uint32_t id,
    uint32_t permissions,
    const char *type,
    uint32_t version,
    const struct spa_dict *props
);

static void ats_pw_client_on_registry_global_remove(
    void *userdata,
    uint32_t id
);

static int ats_pw_client_on_metadata_property(
    void *userdata,
    uint32_t subject,
    const char *key,
    const char *type,
    const char *value
);


static bool ats_pw_copy_string(
    char *destination,
    size_t capacity,
    const char *source
);

static int ats_pw_client_start_observer(
    ats_pw_client *client
);

static void ats_pw_client_stop_observer(
    ats_pw_client *client
);

static void ats_pw_client_on_core_done(
    void *userdata,
    uint32_t id,
    int seq
);

static int ats_pw_client_roundtrip(
    ats_pw_client *client
);


static const struct pw_stream_events
ats_pw_capture_stream_events = {
    PW_VERSION_STREAM_EVENTS,

    .state_changed =
        ats_pw_capture_on_state_changed,

    .param_changed =
        ats_pw_capture_on_param_changed,

    .process =
        ats_pw_capture_on_process,
};


static const struct pw_registry_events
ats_pw_client_registry_events = {
    PW_VERSION_REGISTRY_EVENTS,

    .global =
        ats_pw_client_on_registry_global,

    .global_remove =
        ats_pw_client_on_registry_global_remove,
};


static const struct pw_metadata_events
ats_pw_client_metadata_events = {
    PW_VERSION_METADATA_EVENTS,

    .property =
        ats_pw_client_on_metadata_property,
};


static const struct pw_core_events
ats_pw_client_core_events = {
    PW_VERSION_CORE_EVENTS,

    .done =
        ats_pw_client_on_core_done,
};


static void ats_pw_error_clear(
    ats_pw_error *error
)
{
    if (error == NULL) {
        return;
    }

    error->code = 0;
    error->message[0] = '\0';
}


static void ats_pw_error_set(
    ats_pw_error *error,
    int code,
    const char *operation
)
{
    const char *detail;

    if (error == NULL) {
        return;
    }

    error->code = code;

    detail = spa_strerror(-code);

    if (detail == NULL) {
        detail = "Unknown PipeWire error";
    }

    snprintf(
        error->message,
        sizeof(error->message),
        "%s: %s",
        operation,
        detail
    );
}


static int ats_pw_errno_or_default(
    int fallback
)
{
    if (errno != 0) {
        return errno;
    }

    return fallback;
}


const char *ats_pw_headers_version(void)
{
    return pw_get_headers_version();
}


const char *ats_pw_library_version(void)
{
    return pw_get_library_version();
}


int ats_pw_client_create(
    ats_pw_client **out_client,
    ats_pw_error *error
)
{
    ats_pw_client *client;
    int error_code;

    ats_pw_error_clear(error);

    if (out_client == NULL) {
        ats_pw_error_set(
            error,
            EINVAL,
            "Create PipeWire client"
        );

        return -EINVAL;
    }

    *out_client = NULL;

    client = calloc(
        1,
        sizeof(*client)
    );

    if (client == NULL) {
        ats_pw_error_set(
            error,
            ENOMEM,
            "Allocate PipeWire client"
        );

        return -ENOMEM;
    }

    client->default_metadata_id = PW_ID_ANY;

    pw_init(
        NULL,
        NULL
    );

    client->pipewire_initialized = true;

    errno = 0;

    client->thread_loop = pw_thread_loop_new(
        "ats-pipewire",
        NULL
    );

    if (client->thread_loop == NULL) {
        error_code = ats_pw_errno_or_default(
            ENOMEM
        );

        ats_pw_error_set(
            error,
            error_code,
            "Create PipeWire thread loop"
        );

        goto fail;
    }

    errno = 0;

    client->context = pw_context_new(
        pw_thread_loop_get_loop(
            client->thread_loop
        ),
        NULL,
        0
    );

    if (client->context == NULL) {
        error_code = ats_pw_errno_or_default(
            ENOMEM
        );

        ats_pw_error_set(
            error,
            error_code,
            "Create PipeWire context"
        );

        goto fail;
    }

    *out_client = client;

    return 0;

fail:
    if (client->context != NULL) {
        pw_context_destroy(
            client->context
        );
    }

    if (client->thread_loop != NULL) {
        pw_thread_loop_destroy(
            client->thread_loop
        );
    }

    if (client->pipewire_initialized) {
        pw_deinit();
    }

    free(client);

    return -error_code;
}


int ats_pw_client_start(
    ats_pw_client *client,
    ats_pw_error *error
)
{
    int result;
    int error_code;

    ats_pw_error_clear(error);

    if (client == NULL) {
        ats_pw_error_set(
            error,
            EINVAL,
            "Start PipeWire client"
        );

        return -EINVAL;
    }

    if (client->started) {
        return 0;
    }

    result = pw_thread_loop_start(
        client->thread_loop
    );

    if (result < 0) {
        error_code = -result;

        ats_pw_error_set(
            error,
            error_code,
            "Start PipeWire thread loop"
        );

        return result;
    }

    client->loop_started = true;

    pw_thread_loop_lock(
        client->thread_loop
    );

    errno = 0;

    client->core = pw_context_connect(
        client->context,
        NULL,
        0
    );

    if (client->core == NULL) {
        error_code = ats_pw_errno_or_default(
            EIO
        );

        pw_thread_loop_unlock(
            client->thread_loop
        );

        pw_thread_loop_stop(
            client->thread_loop
        );

        client->loop_started = false;

        ats_pw_error_set(
            error,
            error_code,
            "Connect to PipeWire server"
        );

        return -error_code;
    }

    result = ats_pw_client_start_observer(
        client
    );

    if (result < 0) {
        error_code = -result;

        ats_pw_client_stop_observer(
            client
        );

        (void)pw_core_disconnect(
            client->core
        );

        client->core = NULL;

        pw_thread_loop_unlock(
            client->thread_loop
        );

        pw_thread_loop_stop(
            client->thread_loop
        );

        client->loop_started = false;

        ats_pw_error_set(
            error,
            error_code,
            "Observe PipeWire graph"
        );

        return result;
    }

    pw_thread_loop_unlock(
        client->thread_loop
    );

    client->started = true;

    return 0;
}


int ats_pw_client_stop(
    ats_pw_client *client,
    ats_pw_error *error
)
{
    int disconnect_result = 0;

    ats_pw_error_clear(error);

    if (client == NULL) {
        ats_pw_error_set(
            error,
            EINVAL,
            "Stop PipeWire client"
        );

        return -EINVAL;
    }

    if (client->core != NULL) {
        if (client->loop_started) {
            pw_thread_loop_lock(
                client->thread_loop
            );
        }

        ats_pw_client_stop_observer(
            client
        );

        if (client->core != NULL) {
            disconnect_result =
                pw_core_disconnect(
                    client->core
                );

            client->core = NULL;
        }

        if (client->loop_started) {
            pw_thread_loop_unlock(
                client->thread_loop
            );
        }
    }

    if (client->loop_started) {
        pw_thread_loop_stop(
            client->thread_loop
        );

        client->loop_started = false;
    }

    client->started = false;

    if (disconnect_result < 0) {
        ats_pw_error_set(
            error,
            -disconnect_result,
            "Disconnect from PipeWire server"
        );

        return disconnect_result;
    }

    return 0;
}


void ats_pw_client_destroy(
    ats_pw_client *client
)
{
    if (client == NULL) {
        return;
    }

    (void)ats_pw_client_stop(
        client,
        NULL
    );

    if (client->context != NULL) {
        pw_context_destroy(
            client->context
        );

        client->context = NULL;
    }

    if (client->thread_loop != NULL) {
        pw_thread_loop_destroy(
            client->thread_loop
        );

        client->thread_loop = NULL;
    }

    if (client->pipewire_initialized) {
        pw_deinit();

        client->pipewire_initialized = false;
    }

    free(client);
}


int ats_pw_client_is_started(
    const ats_pw_client *client
)
{
    if (client == NULL) {
        return 0;
    }

    return client->started ? 1 : 0;
}


int ats_pw_client_get_default_source(
    ats_pw_client *client,
    ats_pw_source_info *out_source
)
{
    ats_pw_observed_node *node;

    if (
        client == NULL ||
        out_source == NULL
    ) {
        return -EINVAL;
    }

    memset(
        out_source,
        0,
        sizeof(*out_source)
    );

    if (!client->loop_started) {
        return 0;
    }

    pw_thread_loop_lock(
        client->thread_loop
    );

    if (
        client->default_source_name[0]
        != '\0'
    ) {
        for (
            node = client->nodes;
            node != NULL;
            node = node->next
        ) {
            if (
                strcmp(
                    node->node_name,
                    client->
                        default_source_name
                ) != 0
            ) {
                continue;
            }

            if (
                strcmp(
                    node->media_class,
                    "Audio/Source"
                ) != 0
            ) {
                continue;
            }

            if (
                ats_pw_copy_string(
                    out_source->node_name,
                    sizeof(
                        out_source->
                            node_name
                    ),
                    node->node_name
                )
            ) {
                out_source->available = 1;
            }

            break;
        }
    }

    pw_thread_loop_unlock(
        client->thread_loop
    );

    return 0;
}


int ats_pw_transport_create(
    uint32_t capacity,
    uint32_t max_payload_size,
    ats_pw_transport **out_transport,
    ats_pw_error *error
)
{
    ats_pw_transport *transport;
    size_t payload_storage_size;

    ats_pw_error_clear(error);

    if (
        out_transport == NULL ||
        capacity == 0 ||
        max_payload_size == 0
    ) {
        ats_pw_error_set(
            error,
            EINVAL,
            "Create PipeWire transport"
        );

        return -EINVAL;
    }

    *out_transport = NULL;

    if (
        (size_t)capacity >
        SIZE_MAX / sizeof(ats_pw_transport_record)
    ) {
        ats_pw_error_set(
            error,
            EOVERFLOW,
            "Create PipeWire transport"
        );

        return -EOVERFLOW;
    }

    if (
        (size_t)capacity >
        SIZE_MAX / (size_t)max_payload_size
    ) {
        ats_pw_error_set(
            error,
            EOVERFLOW,
            "Create PipeWire transport"
        );

        return -EOVERFLOW;
    }

    payload_storage_size =
        (size_t)capacity *
        (size_t)max_payload_size;

    transport = calloc(
        1,
        sizeof(*transport)
    );

    if (transport == NULL) {
        ats_pw_error_set(
            error,
            ENOMEM,
            "Allocate PipeWire transport"
        );

        return -ENOMEM;
    }

    transport->records = calloc(
        capacity,
        sizeof(*transport->records)
    );

    if (transport->records == NULL) {
        ats_pw_error_set(
            error,
            ENOMEM,
            "Allocate PipeWire transport metadata"
        );

        free(transport);

        return -ENOMEM;
    }

    transport->payloads = malloc(
        payload_storage_size
    );

    if (transport->payloads == NULL) {
        ats_pw_error_set(
            error,
            ENOMEM,
            "Allocate PipeWire transport payload storage"
        );

        free(transport->records);
        free(transport);

        return -ENOMEM;
    }

    transport->capacity = capacity;
    transport->max_payload_size =
        max_payload_size;

    atomic_init(
        &transport->write_sequence,
        0
    );
    atomic_init(
        &transport->read_sequence,
        0
    );
    atomic_init(
        &transport->dropped_records,
        0
    );

    *out_transport = transport;

    return 0;
}


void ats_pw_transport_destroy(
    ats_pw_transport *transport
)
{
    if (transport == NULL) {
        return;
    }

    free(transport->payloads);
    free(transport->records);
    free(transport);
}


int ats_pw_transport_write(
    ats_pw_transport *transport,
    const ats_pw_transport_record *record,
    const void *payload
)
{
    uint64_t write_sequence;
    uint64_t read_sequence;
    uint32_t index;
    unsigned char *destination;

    if (
        transport == NULL ||
        record == NULL
    ) {
        return -EINVAL;
    }

    if (
        record->payload_size >
        transport->max_payload_size
    ) {
        return -EMSGSIZE;
    }

    if (
        record->payload_size > 0 &&
        payload == NULL
    ) {
        return -EINVAL;
    }

    write_sequence = atomic_load_explicit(
        &transport->write_sequence,
        memory_order_relaxed
    );

    read_sequence = atomic_load_explicit(
        &transport->read_sequence,
        memory_order_acquire
    );

    if (
        write_sequence - read_sequence >=
        transport->capacity
    ) {
        atomic_fetch_add_explicit(
            &transport->dropped_records,
            1,
            memory_order_relaxed
        );

        return -EAGAIN;
    }

    index = (uint32_t)(
        write_sequence %
        transport->capacity
    );

    transport->records[index] = *record;

    if (record->payload_size > 0) {
        destination =
            transport->payloads +
            (
                (size_t)index *
                transport->max_payload_size
            );

        memcpy(
            destination,
            payload,
            record->payload_size
        );
    }

    /*
     * Publish the completed metadata + payload only after
     * every slot write above is complete.
     */
    atomic_store_explicit(
        &transport->write_sequence,
        write_sequence + 1,
        memory_order_release
    );

    return 0;
}


int ats_pw_transport_read(
    ats_pw_transport *transport,
    ats_pw_transport_record *out_record,
    void *out_payload,
    uint32_t out_payload_capacity
)
{
    uint64_t read_sequence;
    uint64_t write_sequence;
    uint32_t index;
    const ats_pw_transport_record *record;
    const unsigned char *source;

    if (
        transport == NULL ||
        out_record == NULL
    ) {
        return -EINVAL;
    }

    read_sequence = atomic_load_explicit(
        &transport->read_sequence,
        memory_order_relaxed
    );

    write_sequence = atomic_load_explicit(
        &transport->write_sequence,
        memory_order_acquire
    );

    if (read_sequence == write_sequence) {
        return ATS_PW_TRANSPORT_READ_EMPTY;
    }

    index = (uint32_t)(
        read_sequence %
        transport->capacity
    );

    record = &transport->records[index];

    if (
        record->payload_size >
        out_payload_capacity
    ) {
        return -ENOBUFS;
    }

    if (
        record->payload_size > 0 &&
        out_payload == NULL
    ) {
        return -EINVAL;
    }

    *out_record = *record;

    if (record->payload_size > 0) {
        source =
            transport->payloads +
            (
                (size_t)index *
                transport->max_payload_size
            );

        memcpy(
            out_payload,
            source,
            record->payload_size
        );
    }

    /*
     * Release the slot only after the consumer has copied
     * all metadata and payload bytes out of it.
     */
    atomic_store_explicit(
        &transport->read_sequence,
        read_sequence + 1,
        memory_order_release
    );

    return ATS_PW_TRANSPORT_READ_OK;
}


void ats_pw_transport_get_stats(
    const ats_pw_transport *transport,
    ats_pw_transport_stats *out_stats
)
{
    uint64_t write_sequence;
    uint64_t read_sequence;

    if (
        transport == NULL ||
        out_stats == NULL
    ) {
        return;
    }

    write_sequence = atomic_load_explicit(
        &transport->write_sequence,
        memory_order_acquire
    );

    read_sequence = atomic_load_explicit(
        &transport->read_sequence,
        memory_order_acquire
    );

    out_stats->written_records =
        write_sequence;

    out_stats->read_records =
        read_sequence;

    out_stats->dropped_records =
        atomic_load_explicit(
            &transport->dropped_records,
            memory_order_relaxed
        );

    out_stats->depth = (uint32_t)(
        write_sequence -
        read_sequence
    );

    out_stats->capacity =
        transport->capacity;

    out_stats->max_payload_size =
        transport->max_payload_size;
}


static bool ats_pw_copy_string(
    char *destination,
    size_t capacity,
    const char *source
)
{
    size_t length;

    if (
        destination == NULL ||
        capacity == 0 ||
        source == NULL
    ) {
        return false;
    }

    length = strlen(source);

    if (length >= capacity) {
        return false;
    }

    memcpy(
        destination,
        source,
        length + 1
    );

    return true;
}


static void ats_pw_client_remove_node(
    ats_pw_client *client,
    uint32_t id
)
{
    ats_pw_observed_node **current;

    current = &client->nodes;

    while (*current != NULL) {
        ats_pw_observed_node *node =
            *current;

        if (node->id == id) {
            *current = node->next;
            free(node);
            return;
        }

        current = &node->next;
    }
}


static void ats_pw_client_clear_nodes(
    ats_pw_client *client
)
{
    while (client->nodes != NULL) {
        ats_pw_observed_node *node =
            client->nodes;

        client->nodes = node->next;

        free(node);
    }
}


static void ats_pw_client_add_node(
    ats_pw_client *client,
    uint32_t id,
    const struct spa_dict *props
)
{
    const char *node_name;
    const char *media_class;
    ats_pw_observed_node *node;

    if (props == NULL) {
        return;
    }

    node_name = spa_dict_lookup(
        props,
        PW_KEY_NODE_NAME
    );

    media_class = spa_dict_lookup(
        props,
        PW_KEY_MEDIA_CLASS
    );

    if (
        node_name == NULL ||
        media_class == NULL
    ) {
        return;
    }

    node = calloc(
        1,
        sizeof(*node)
    );

    if (node == NULL) {
        return;
    }

    if (
        !ats_pw_copy_string(
            node->node_name,
            sizeof(node->node_name),
            node_name
        ) ||
        !ats_pw_copy_string(
            node->media_class,
            sizeof(node->media_class),
            media_class
        )
    ) {
        free(node);
        return;
    }

    node->id = id;

    ats_pw_client_remove_node(
        client,
        id
    );

    node->next = client->nodes;
    client->nodes = node;
}


static void ats_pw_client_set_default_source(
    ats_pw_client *client,
    const char *value
)
{
    struct spa_json iterator;
    struct spa_json object;

    const char *token;
    int length;

    char key[64];
    char node_name[
        ATS_PW_NODE_NAME_CAPACITY
    ];

    client->default_source_name[0] =
        '\0';

    if (value == NULL) {
        return;
    }

    length = spa_json_begin(
        &iterator,
        value,
        strlen(value),
        &token
    );

    if (
        length <= 0 ||
        !spa_json_is_object(
            token,
            length
        )
    ) {
        return;
    }

    spa_json_enter(
        &iterator,
        &object
    );

    while (
        (
            length =
                spa_json_object_next(
                    &object,
                    key,
                    sizeof(key),
                    &token
                )
        ) > 0
    ) {
        if (strcmp(key, "name") != 0) {
            continue;
        }

        if (
            !spa_json_is_string(
                token,
                length
            )
        ) {
            return;
        }

        if (
            spa_json_parse_stringn(
                token,
                length,
                node_name,
                sizeof(node_name)
            ) <= 0
        ) {
            return;
        }

        (void)ats_pw_copy_string(
            client->default_source_name,
            sizeof(
                client->default_source_name
            ),
            node_name
        );

        return;
    }
}


static int ats_pw_client_on_metadata_property(
    void *userdata,
    uint32_t subject,
    const char *key,
    const char *type,
    const char *value
)
{
    ats_pw_client *client = userdata;

    (void)type;

    if (subject != PW_ID_CORE) {
        return 0;
    }

    /*
     * NULL key means metadata for the subject
     * was cleared.
     */
    if (key == NULL) {
        client->default_source_name[0] =
            '\0';

        return 0;
    }

    if (
        strcmp(
            key,
            "default.audio.source"
        ) != 0
    ) {
        return 0;
    }

    ats_pw_client_set_default_source(
        client,
        value
    );

    return 0;
}


static void ats_pw_client_on_registry_global(
    void *userdata,
    uint32_t id,
    uint32_t permissions,
    const char *type,
    uint32_t version,
    const struct spa_dict *props
)
{
    ats_pw_client *client = userdata;

    (void)permissions;

    if (
        strcmp(
            type,
            PW_TYPE_INTERFACE_Node
        ) == 0
    ) {
        ats_pw_client_add_node(
            client,
            id,
            props
        );

        return;
    }

    if (
        strcmp(
            type,
            PW_TYPE_INTERFACE_Metadata
        ) != 0
    ) {
        return;
    }

    if (
        client->default_metadata != NULL ||
        props == NULL
    ) {
        return;
    }

    const char *metadata_name =
        spa_dict_lookup(
            props,
            PW_KEY_METADATA_NAME
        );

    if (
        metadata_name == NULL ||
        strcmp(
            metadata_name,
            "default"
        ) != 0
    ) {
        return;
    }

    uint32_t bind_version =
        version < PW_VERSION_METADATA
            ? version
            : PW_VERSION_METADATA;

    client->default_metadata =
        pw_registry_bind(
            client->registry,
            id,
            PW_TYPE_INTERFACE_Metadata,
            bind_version,
            0
        );

    if (
        client->default_metadata == NULL
    ) {
        return;
    }

    client->default_metadata_id = id;

    int result =
        pw_metadata_add_listener(
            client->default_metadata,
            &client->metadata_listener,
            &ats_pw_client_metadata_events,
            client
        );

    if (result < 0) {
        pw_proxy_destroy(
            (struct pw_proxy *)
                client->default_metadata
        );

        client->default_metadata = NULL;
        client->default_metadata_id =
            PW_ID_ANY;
    }
}


static void ats_pw_client_on_registry_global_remove(
    void *userdata,
    uint32_t id
)
{
    ats_pw_client *client = userdata;

    ats_pw_client_remove_node(
        client,
        id
    );

    if (
        id !=
        client->default_metadata_id
    ) {
        return;
    }

    if (
        client->default_metadata != NULL
    ) {
        spa_hook_remove(
            &client->metadata_listener
        );

        pw_proxy_destroy(
            (struct pw_proxy *)
                client->default_metadata
        );

        client->default_metadata = NULL;
    }

    client->default_metadata_id =
        PW_ID_ANY;

    client->default_source_name[0] =
        '\0';
}


static void ats_pw_client_on_core_done(
    void *userdata,
    uint32_t id,
    int seq
)
{
    ats_pw_client *client = userdata;

    if (
        id != PW_ID_CORE ||
        !client->observer_sync_pending ||
        seq != client->observer_sync_seq
    ) {
        return;
    }

    client->observer_sync_pending = false;

    pw_thread_loop_signal(
        client->thread_loop,
        false
    );
}


static int ats_pw_client_roundtrip(
    ats_pw_client *client
)
{
    struct timespec deadline;
    int result;

    result = pw_core_sync(
        client->core,
        PW_ID_CORE,
        0
    );

    if (result < 0) {
        return result;
    }

    client->observer_sync_seq = result;
    client->observer_sync_pending = true;

    result = pw_thread_loop_get_time(
        client->thread_loop,
        &deadline,
        ATS_PW_OBSERVER_SYNC_TIMEOUT_NS
    );

    if (result < 0) {
        client->observer_sync_pending =
            false;

        return result;
    }

    while (
        client->observer_sync_pending
    ) {
        result =
            pw_thread_loop_timed_wait_full(
                client->thread_loop,
                &deadline
            );

        if (result < 0) {
            client->observer_sync_pending =
                false;

            return result;
        }
    }

    return 0;
}


static int ats_pw_client_start_observer(
    ats_pw_client *client
)
{
    int result;
    int error_code;

    result = pw_core_add_listener(
        client->core,
        &client->core_listener,
        &ats_pw_client_core_events,
        client
    );

    if (result < 0) {
        return result;
    }

    client->core_listener_added = true;

    errno = 0;

    client->registry =
        pw_core_get_registry(
            client->core,
            PW_VERSION_REGISTRY,
            0
        );

    if (client->registry == NULL) {
        error_code =
            ats_pw_errno_or_default(
                EIO
            );

        return -error_code;
    }

    result = pw_registry_add_listener(
        client->registry,
        &client->registry_listener,
        &ats_pw_client_registry_events,
        client
    );

    if (result < 0) {
        return result;
    }

    client->registry_listener_added = true;

    /*
     * Roundtrip 1:
     * receive the initial registry snapshot.
     * The default Metadata object is bound
     * from the registry callback.
     */
    result = ats_pw_client_roundtrip(
        client
    );

    if (result < 0) {
        return result;
    }

    /*
     * Roundtrip 2:
     * ensure initial properties emitted by
     * the Metadata binding have arrived.
     */
    result = ats_pw_client_roundtrip(
        client
    );

    if (result < 0) {
        return result;
    }

    return 0;
}


static void ats_pw_client_stop_observer(
    ats_pw_client *client
)
{
    if (
        client->default_metadata != NULL
    ) {
        spa_hook_remove(
            &client->metadata_listener
        );

        pw_proxy_destroy(
            (struct pw_proxy *)
                client->default_metadata
        );

        client->default_metadata = NULL;
    }

    client->default_metadata_id =
        PW_ID_ANY;

    if (client->registry != NULL) {
        if (client->registry_listener_added) {
            spa_hook_remove(
                &client->registry_listener
            );

            client->registry_listener_added = false;
        }

        pw_proxy_destroy(
            (struct pw_proxy *)
                client->registry
        );

        client->registry = NULL;
    }

    client->observer_sync_pending = false;
    client->observer_sync_seq = 0;

    if (client->core_listener_added) {
        spa_hook_remove(
            &client->core_listener
        );

        client->core_listener_added = false;
    }

    ats_pw_client_clear_nodes(
        client
    );

    client->default_source_name[0] =
        '\0';
}


static void ats_pw_capture_on_state_changed(
    void *userdata,
    enum pw_stream_state old_state,
    enum pw_stream_state state,
    const char *error
)
{
    ats_pw_capture *capture = userdata;

    (void)old_state;
    (void)error;

    atomic_store_explicit(
        &capture->stream_state,
        (int)state,
        memory_order_release
    );
}


static void ats_pw_capture_on_param_changed(
    void *userdata,
    uint32_t id,
    const struct spa_pod *param
)
{
    ats_pw_capture *capture = userdata;
    struct spa_audio_info_raw format = {0};

    if (
        param == NULL ||
        id != SPA_PARAM_Format
    ) {
        return;
    }

    if (
        spa_format_audio_raw_parse(
            param,
            &format
        ) < 0
    ) {
        return;
    }

    if (
        format.format !=
        SPA_AUDIO_FORMAT_S16_LE
    ) {
        return;
    }

    if (
        format.rate == 0 ||
        format.channels == 0
    ) {
        return;
    }

    atomic_store_explicit(
        &capture->sample_rate,
        format.rate,
        memory_order_release
    );

    atomic_store_explicit(
        &capture->channels,
        format.channels,
        memory_order_release
    );

    atomic_store_explicit(
        &capture->sample_type,
        ATS_PW_SAMPLE_TYPE_INT16,
        memory_order_release
    );
}


static void ats_pw_capture_on_process(
    void *userdata
)
{
    ats_pw_capture *capture = userdata;
    struct pw_buffer *pw_buffer;
    struct spa_buffer *buffer;
    struct spa_data *data;
    struct spa_chunk *chunk;

    ats_pw_transport_record record = {0};

    uint32_t sample_rate;
    uint32_t channels;
    uint32_t bytes_per_frame;
    uint32_t payload_size;

    const unsigned char *payload;
    int write_result;

    atomic_fetch_add_explicit(
        &capture->process_callbacks,
        1,
        memory_order_relaxed
    );

    pw_buffer = pw_stream_dequeue_buffer(
        capture->stream
    );

    if (pw_buffer == NULL) {
        return;
    }

    buffer = pw_buffer->buffer;

    if (
        buffer == NULL ||
        buffer->n_datas == 0
    ) {
        atomic_fetch_add_explicit(
            &capture->invalid_buffers,
            1,
            memory_order_relaxed
        );

        goto requeue;
    }

    data = &buffer->datas[0];
    chunk = data->chunk;

    if (
        data->data == NULL ||
        chunk == NULL
    ) {
        atomic_fetch_add_explicit(
            &capture->invalid_buffers,
            1,
            memory_order_relaxed
        );

        goto requeue;
    }

    if (
        chunk->offset > data->maxsize ||
        chunk->size >
            data->maxsize - chunk->offset
    ) {
        atomic_fetch_add_explicit(
            &capture->invalid_buffers,
            1,
            memory_order_relaxed
        );

        goto requeue;
    }

    if (chunk->size == 0) {
        goto requeue;
    }

    sample_rate = atomic_load_explicit(
        &capture->sample_rate,
        memory_order_acquire
    );

    channels = atomic_load_explicit(
        &capture->channels,
        memory_order_acquire
    );

    if (
        sample_rate == 0 ||
        channels == 0
    ) {
        atomic_fetch_add_explicit(
            &capture->invalid_buffers,
            1,
            memory_order_relaxed
        );

        goto requeue;
    }

    bytes_per_frame =
        channels * sizeof(int16_t);

    payload_size = chunk->size;

    if (
        bytes_per_frame == 0 ||
        payload_size % bytes_per_frame != 0
    ) {
        atomic_fetch_add_explicit(
            &capture->invalid_buffers,
            1,
            memory_order_relaxed
        );

        goto requeue;
    }

    payload =
        (const unsigned char *)
        data->data +
        chunk->offset;

    record.timestamp_ns =
        pw_buffer->time;

    record.sample_rate =
        sample_rate;

    record.channels =
        channels;

    record.sample_type =
        ATS_PW_SAMPLE_TYPE_INT16;

    record.frame_count =
        payload_size /
        bytes_per_frame;

    record.payload_size =
        payload_size;

    write_result = ats_pw_transport_write(
        capture->transport,
        &record,
        payload
    );

    if (write_result == -EMSGSIZE) {
        atomic_fetch_add_explicit(
            &capture->oversized_buffers,
            1,
            memory_order_relaxed
        );
    } else if (
        write_result < 0 &&
        write_result != -EAGAIN
    ) {
        atomic_fetch_add_explicit(
            &capture->invalid_buffers,
            1,
            memory_order_relaxed
        );
    }

requeue:
    (void)pw_stream_queue_buffer(
        capture->stream,
        pw_buffer
    );
}


int ats_pw_microphone_create(
    ats_pw_client *client,
    uint32_t queue_capacity,
    uint32_t max_payload_size,
    ats_pw_capture **out_capture,
    ats_pw_error *error
)
{
    ats_pw_capture *capture;
    int result;

    ats_pw_error_clear(error);

    if (
        client == NULL ||
        out_capture == NULL
    ) {
        ats_pw_error_set(
            error,
            EINVAL,
            "Create PipeWire microphone capture"
        );

        return -EINVAL;
    }

    *out_capture = NULL;

    capture = calloc(
        1,
        sizeof(*capture)
    );

    if (capture == NULL) {
        ats_pw_error_set(
            error,
            ENOMEM,
            "Allocate PipeWire microphone capture"
        );

        return -ENOMEM;
    }

    capture->client = client;

    atomic_init(
        &capture->stream_state,
        ATS_PW_CAPTURE_STATE_UNCONNECTED
    );

    atomic_init(
        &capture->sample_rate,
        0
    );

    atomic_init(
        &capture->channels,
        0
    );

    atomic_init(
        &capture->sample_type,
        0
    );

    atomic_init(
        &capture->process_callbacks,
        0
    );

    atomic_init(
        &capture->invalid_buffers,
        0
    );

    atomic_init(
        &capture->oversized_buffers,
        0
    );

    result = ats_pw_transport_create(
        queue_capacity,
        max_payload_size,
        &capture->transport,
        error
    );

    if (result < 0) {
        free(capture);

        return result;
    }

    *out_capture = capture;

    return 0;
}


int ats_pw_capture_start(
    ats_pw_capture *capture,
    ats_pw_error *error
)
{
    struct pw_properties *properties;
    const struct spa_pod *params[1];

    ats_pw_source_info source = {0};

    uint8_t parameter_buffer[1024];

    struct spa_pod_builder builder =
        SPA_POD_BUILDER_INIT(
            parameter_buffer,
            sizeof(parameter_buffer)
        );

    int result;
    int error_code;

    ats_pw_error_clear(error);

    if (capture == NULL) {
        ats_pw_error_set(
            error,
            EINVAL,
            "Start PipeWire capture"
        );

        return -EINVAL;
    }

    if (capture->stream != NULL) {
        return 0;
    }

    if (capture->ever_started) {
        ats_pw_error_set(
            error,
            EALREADY,
            "Restart PipeWire capture"
        );

        return -EALREADY;
    }

    if (!capture->client->started) {
        ats_pw_error_set(
            error,
            ENOTCONN,
            "Start PipeWire capture"
        );

        return -ENOTCONN;
    }

    result = ats_pw_client_get_default_source(
        capture->client,
        &source
    );

    if (result < 0) {
        ats_pw_error_set(
            error,
            -result,
            "Resolve PipeWire microphone source"
        );

        return result;
    }

    if (!source.available) {
        ats_pw_error_set(
            error,
            ENODEV,
            "Start PipeWire microphone capture"
        );

        return -ENODEV;
    }

    properties = pw_properties_new(
        PW_KEY_MEDIA_TYPE,
        "Audio",

        PW_KEY_MEDIA_CATEGORY,
        "Capture",

        PW_KEY_MEDIA_ROLE,
        "Communication",

        PW_KEY_STREAM_CAPTURE_SINK,
        "false",

        PW_KEY_TARGET_OBJECT,
        source.node_name,

        NULL
    );

    if (properties == NULL) {
        ats_pw_error_set(
            error,
            ENOMEM,
            "Create PipeWire stream properties"
        );

        return -ENOMEM;
    }

    pw_thread_loop_lock(
        capture->client->thread_loop
    );

    errno = 0;

    capture->stream = pw_stream_new(
        capture->client->core,
        "Audio Transcription Service Microphone",
        properties
    );

    if (capture->stream == NULL) {
        error_code =
            ats_pw_errno_or_default(
                ENOMEM
            );

        pw_thread_loop_unlock(
            capture->client->thread_loop
        );

        ats_pw_error_set(
            error,
            error_code,
            "Create PipeWire microphone stream"
        );

        return -error_code;
    }

    pw_stream_add_listener(
        capture->stream,
        &capture->stream_listener,
        &ats_pw_capture_stream_events,
        capture
    );

    capture->listener_added = true;

    /*
     * Force application-visible PCM to S16LE mono,
     * but allow PipeWire to negotiate the graph rate.
     */
    params[0] =
        spa_format_audio_raw_build(
            &builder,
            SPA_PARAM_EnumFormat,
            &SPA_AUDIO_INFO_RAW_INIT(
                .format =
                    SPA_AUDIO_FORMAT_S16_LE,
                .channels = 1
            )
        );

    result = pw_stream_connect(
        capture->stream,
        PW_DIRECTION_INPUT,
        PW_ID_ANY,

        PW_STREAM_FLAG_AUTOCONNECT |
        PW_STREAM_FLAG_MAP_BUFFERS |
        PW_STREAM_FLAG_RT_PROCESS,

        params,
        1
    );

    if (result < 0) {
        if (capture->listener_added) {
            spa_hook_remove(
                &capture->stream_listener
            );

            capture->listener_added =
                false;
        }

        pw_stream_destroy(
            capture->stream
        );

        capture->stream = NULL;

        pw_thread_loop_unlock(
            capture->client->thread_loop
        );

        ats_pw_error_set(
            error,
            -result,
            "Connect PipeWire microphone stream"
        );

        return result;
    }

    pw_thread_loop_unlock(
        capture->client->thread_loop
    );

    capture->ever_started = true;

    return 0;
}


int ats_pw_capture_stop(
    ats_pw_capture *capture,
    ats_pw_error *error
)
{
    ats_pw_error_clear(error);

    if (capture == NULL) {
        ats_pw_error_set(
            error,
            EINVAL,
            "Stop PipeWire capture"
        );

        return -EINVAL;
    }

    if (capture->stream == NULL) {
        return 0;
    }

    pw_thread_loop_lock(
        capture->client->thread_loop
    );

    if (capture->listener_added) {
        spa_hook_remove(
            &capture->stream_listener
        );

        capture->listener_added = false;
    }

    pw_stream_destroy(
        capture->stream
    );

    capture->stream = NULL;

    pw_thread_loop_unlock(
        capture->client->thread_loop
    );

    atomic_store_explicit(
        &capture->stream_state,
        ATS_PW_CAPTURE_STATE_UNCONNECTED,
        memory_order_release
    );

    return 0;
}


void ats_pw_capture_destroy(
    ats_pw_capture *capture
)
{
    if (capture == NULL) {
        return;
    }

    (void)ats_pw_capture_stop(
        capture,
        NULL
    );

    ats_pw_transport_destroy(
        capture->transport
    );

    capture->transport = NULL;

    free(capture);
}


int ats_pw_capture_read(
    ats_pw_capture *capture,
    ats_pw_transport_record *out_record,
    void *out_payload,
    uint32_t out_payload_capacity
)
{
    if (capture == NULL) {
        return -EINVAL;
    }

    return ats_pw_transport_read(
        capture->transport,
        out_record,
        out_payload,
        out_payload_capacity
    );
}


void ats_pw_capture_get_stats(
    const ats_pw_capture *capture,
    ats_pw_capture_stats *out_stats
)
{
    if (
        capture == NULL ||
        out_stats == NULL
    ) {
        return;
    }

    memset(
        out_stats,
        0,
        sizeof(*out_stats)
    );

    out_stats->stream_state =
        atomic_load_explicit(
            &capture->stream_state,
            memory_order_acquire
        );

    out_stats->sample_rate =
        atomic_load_explicit(
            &capture->sample_rate,
            memory_order_acquire
        );

    out_stats->channels =
        atomic_load_explicit(
            &capture->channels,
            memory_order_acquire
        );

    out_stats->sample_type =
        atomic_load_explicit(
            &capture->sample_type,
            memory_order_acquire
        );

    out_stats->process_callbacks =
        atomic_load_explicit(
            &capture->process_callbacks,
            memory_order_relaxed
        );

    out_stats->invalid_buffers =
        atomic_load_explicit(
            &capture->invalid_buffers,
            memory_order_relaxed
        );

    out_stats->oversized_buffers =
        atomic_load_explicit(
            &capture->oversized_buffers,
            memory_order_relaxed
        );

    ats_pw_transport_get_stats(
        capture->transport,
        &out_stats->transport
    );
}