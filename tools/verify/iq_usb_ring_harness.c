#include <assert.h>
#include <stdio.h>
#include "iq_usb_ring.h"

/* This is deliberately not mapped as process memory. The queue must never
 * dereference IQ, even with many completions, drops and lifecycle transitions.
 */
#define DMA_BASE 0x80900000u
static struct iq_usb_ring ring;
static struct iq_usb_request a, b, c, send;

static void begin(uint32_t generation)
{
    assert(iq_usb_init(&ring, DMA_BASE, 24000, 8000, 3, generation));
}

int main(void)
{
    uint32_t i;
    struct iq_token old;
    assert(!iq_usb_init(&ring, DMA_BASE+1, 24000, 8000, 3, 1));
    assert(!iq_usb_init(&ring, DMA_BASE, 23999, 8000, 3, 1));
    assert(!iq_usb_init(&ring, 0xfffff000, 24000, 8000, 3, 1));
    assert(!iq_usb_init(&ring, DMA_BASE, 24000, 8001, 3, 1));
    assert(!iq_usb_init(&ring, DMA_BASE, 24000, 8000, 65, 1));
    assert(!iq_usb_init(&ring, DMA_BASE, 24000, 8000, 3, 0));
    begin(1);
    assert(iq_capture_acquire(&ring, &a) && a.dma_address == DMA_BASE && a.bytes == 8000);
    assert(iq_capture_acquire(&ring, &b) && b.dma_address == DMA_BASE+8000);
    assert(iq_capture_acquire(&ring, &c) && c.dma_address == DMA_BASE+16000);
    assert(!iq_capture_acquire(&ring, &send) && ring.stats.overrun_drops == 1);
    assert(iq_capture_publish(&ring, b.token, 8000));
    assert(!iq_usb_take(&ring, &send)); /* wait for earlier DMA */
    assert(!iq_capture_publish(&ring, a.token, 7999));
    assert(!iq_capture_publish(&ring, a.token, 8004));
    assert(iq_capture_publish(&ring, a.token, 8000));
    assert(iq_usb_take(&ring, &send) && send.token.sequence == a.token.sequence);
    assert(send.dma_address == a.dma_address && send.bytes == 8000);
    assert(iq_usb_take(&ring, &send) && send.token.sequence == b.token.sequence);
    assert(!iq_usb_take(&ring, &send));
    assert(!iq_capture_acquire(&ring, &send)); /* USB still owns both */
    old = a.token;
    ++old.generation;
    assert(!iq_usb_complete(&ring, old, 1));
    assert(iq_usb_complete(&ring, b.token, 0)); /* failed transfer, no retry */
    assert(iq_capture_acquire(&ring, &send) && send.dma_address == b.dma_address);
    assert(iq_capture_publish(&ring, c.token, 8000));
    iq_usb_stop(&ring); /* drop ready C, wait for A and in-progress capture */
    assert(!iq_usb_drained(&ring));
    assert(!iq_capture_acquire(&ring, &b) && !iq_usb_take(&ring, &b));
    assert(iq_capture_publish(&ring, send.token, 8000));
    assert(iq_usb_complete(&ring, a.token, 1));
    assert(iq_usb_drained(&ring) && ring.stats.completed_bytes == 8000);
    assert(ring.stats.usb_failures == 1 && ring.stats.stop_drops == 2);
    assert(!iq_usb_complete(&ring, a.token, 1)); /* duplicate completion */
    begin(2);
    assert(iq_capture_acquire(&ring, &b));
    assert(iq_capture_publish(&ring, b.token, 4000));
    assert(iq_usb_take(&ring, &send) && send.bytes == 4000);
    assert(!iq_usb_complete(&ring, a.token, 1)); /* previous session */
    assert(iq_usb_complete(&ring, send.token, 1));
    assert(ring.stats.completed_bytes == 4000);
    for (i = 0; i < 10000; ++i) {
        assert(iq_capture_acquire(&ring, &a));
        assert(iq_capture_publish(&ring, a.token, 8000));
        assert(iq_usb_take(&ring, &b));
        assert(a.dma_address == b.dma_address && b.bytes == 8000);
        assert(iq_usb_complete(&ring, b.token, 1));
    }
    assert(ring.stats.completed_bytes == 80004000ull);
    assert(iq_capture_acquire(&ring, &a));
    assert(iq_capture_abort(&ring, a.token));
    ring.next_sequence = UINT32_MAX;
    assert(!iq_capture_acquire(&ring, &a) && ring.stats.sequence_exhausted == 1);
    assert(iq_usb_drained(&ring));
    puts("passed: bounds, DMA ownership, ordered submits, delayed/stale completion, drops, stop/drain, 10000 cycles; no payload mapping");
    return 0;
}
