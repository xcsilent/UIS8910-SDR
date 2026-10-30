#ifndef SDR_CP_STREAM_MAILBOX_H
#define SDR_CP_STREAM_MAILBOX_H
#include <stdint.h>

struct cp_mailbox_cache {
    void *context;
    void (*clean)(void *, const volatile void *, uint32_t);
    void (*invalidate)(void *, const volatile void *, uint32_t);
    void (*barrier)(void *);
};
struct cp_stream_reply { uint32_t phase, error, value0, value1; };
struct cp_stream_mailbox {
    volatile uint32_t *request, *response;
    struct cp_mailbox_cache cache;
    uint32_t generation, completed, pending, operation, block, begun_ms, timeout_ms, fault;
};
enum cp_mailbox_result { CP_MBOX_REJECTED=-3, CP_MBOX_EXPIRED=-2, CP_MBOX_BAD_REPLY=-1,
                         CP_MBOX_WAIT=0, CP_MBOX_DONE=1 };
/* Two distinct 32-byte cache lines, freshly zeroed while CP is idle. Never
 * reset a live mailbox or discard an unresolved command to reuse its memory.
 * Context has one AP worker owner; CP owns response, AP owns request.
 */
int cp_stream_mailbox_init(struct cp_stream_mailbox *, volatile uint32_t *lines,
                           uint32_t generation, struct cp_mailbox_cache);
int cp_stream_mailbox_begin(struct cp_stream_mailbox *, uint32_t operation,
                            uint32_t block, uint32_t now_ms, uint32_t timeout_ms);
enum cp_mailbox_result cp_stream_mailbox_poll(struct cp_stream_mailbox *,
                                              uint32_t now_ms, struct cp_stream_reply *);
#endif
