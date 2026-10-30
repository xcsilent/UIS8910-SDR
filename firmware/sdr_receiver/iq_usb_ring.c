#include "iq_usb_ring.h"

int iq_usb_init(struct iq_usb_ring *r, uint32_t base, uint32_t region_bytes,
                uint32_t block_bytes, uint32_t slots, uint32_t generation)
{
    uint32_t i;
    volatile struct iq_usb_stats *stats;
    if (!r || !generation || !base || (base & 3u) || !block_bytes ||
        (block_bytes & 3u) || block_bytes > 65536u || !slots ||
        slots > IQ_USB_MAX_SLOTS || slots * block_bytes > region_bytes ||
        region_bytes > UINT32_MAX - base)
        return 0;
    r->base = base;
    r->block_bytes = block_bytes;
    r->slots = slots;
    r->generation = generation;
    r->next_sequence = 1;
    r->running = 1;
    /* Explicit startup stores avoid an implicit libc memset on bare ARM. */
    stats = &r->stats;
    stats->acquired = stats->overrun_drops = stats->submitted = 0;
    stats->completed = stats->usb_failures = stats->stop_drops = 0;
    stats->stale_events = stats->sequence_exhausted = 0;
    stats->completed_bytes = 0;
    for (i = 0; i < IQ_USB_MAX_SLOTS; ++i) {
        volatile struct iq_slot *s = &r->slot[i];
        s->state = s->sequence = s->bytes = 0;
    }
    return 1;
}

static struct iq_slot *owned(struct iq_usb_ring *r, struct iq_token t, uint32_t state)
{
    if (t.generation == r->generation && t.slot < r->slots &&
        r->slot[t.slot].sequence == t.sequence && r->slot[t.slot].state == state)
        return &r->slot[t.slot];
    ++r->stats.stale_events;
    return 0;
}

static void request(const struct iq_usb_ring *r, uint32_t slot, struct iq_usb_request *out)
{
    out->token = (struct iq_token){r->generation, r->slot[slot].sequence, slot};
    out->dma_address = r->base + slot * r->block_bytes;
    out->bytes = r->slot[slot].bytes;
}

int iq_capture_acquire(struct iq_usb_ring *r, struct iq_usb_request *out)
{
    uint32_t i, sequence;
    if (!out || !r->running)
        return 0;
    /* Never wrap a sequence into an old completion token. */
    if (r->next_sequence == UINT32_MAX) {
        r->running = 0;
        ++r->stats.sequence_exhausted;
        return 0;
    }
    sequence = r->next_sequence++;
    /* May choose any FREE slot. A cyclic capture engine must respect this
     * returned address, or divert/drop its input without touching busy slots.
     */
    for (i = 0; i < r->slots; ++i) {
        if (r->slot[i].state != IQ_FREE)
            continue;
        r->slot[i] = (struct iq_slot){IQ_CAPTURING, sequence, r->block_bytes};
        ++r->stats.acquired;
        request(r, i, out);
        return 1;
    }
    ++r->stats.overrun_drops;
    return 0;
}

int iq_capture_publish(struct iq_usb_ring *r, struct iq_token token, uint32_t bytes)
{
    struct iq_slot *s = owned(r, token, IQ_CAPTURING);
    if (!s || !bytes || bytes > r->block_bytes || (bytes & 3u))
        return 0;
    s->bytes = bytes;
    if (!r->running) {
        s->state = IQ_FREE;
        ++r->stats.stop_drops;
    } else {
        s->state = IQ_READY;
    }
    return 1;
}

int iq_capture_abort(struct iq_usb_ring *r, struct iq_token token)
{
    struct iq_slot *s = owned(r, token, IQ_CAPTURING);
    if (!s)
        return 0;
    s->state = IQ_FREE;
    ++r->stats.stop_drops;
    return 1;
}

int iq_usb_take(struct iq_usb_ring *r, struct iq_usb_request *out)
{
    uint32_t i, earliest = UINT32_MAX, chosen = IQ_USB_MAX_SLOTS;
    if (!out || !r->running)
        return 0;
    for (i = 0; i < r->slots; ++i) {
        /* A delayed capture completion must not reorder the sample stream. */
        if ((r->slot[i].state == IQ_READY || r->slot[i].state == IQ_CAPTURING) &&
            r->slot[i].sequence < earliest) {
            earliest = r->slot[i].sequence;
            chosen = i;
        }
    }
    if (chosen == IQ_USB_MAX_SLOTS || r->slot[chosen].state != IQ_READY)
        return 0;
    r->slot[chosen].state = IQ_USB;
    ++r->stats.submitted;
    request(r, chosen, out);
    return 1;
}

int iq_usb_complete(struct iq_usb_ring *r, struct iq_token token, int success)
{
    struct iq_slot *s = owned(r, token, IQ_USB);
    if (!s)
        return 0;
    if (success) {
        ++r->stats.completed;
        r->stats.completed_bytes += s->bytes;
    } else {
        ++r->stats.usb_failures;
    }
    s->state = IQ_FREE;
    return 1;
}

void iq_usb_stop(struct iq_usb_ring *r)
{
    uint32_t i;
    r->running = 0;
    for (i = 0; i < r->slots; ++i) {
        if (r->slot[i].state == IQ_READY) {
            r->slot[i].state = IQ_FREE;
            ++r->stats.stop_drops;
        }
    }
}

int iq_usb_drained(const struct iq_usb_ring *r)
{
    uint32_t i;
    for (i = 0; i < r->slots; ++i)
        if (r->slot[i].state != IQ_FREE)
            return 0;
    return 1;
}
