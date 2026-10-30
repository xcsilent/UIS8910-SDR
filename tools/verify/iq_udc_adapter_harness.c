#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "iq_udc_adapter.h"

/* Fake request retains private tail bytes: catches accidental prefix-sized
 * allocations/clears. Payload addresses are never mapped or read by the CPU.
 */
struct fake_xfer { struct sdr_usb_xfer public; uint32_t private_tail[4]; };
struct fake_udc {
    struct sdr_udc udc;
    struct fake_xfer xfer[IQ_USB_MAX_SLOTS];
    struct sdr_usb_xfer *queued[IQ_USB_MAX_SLOTS];
    unsigned allocated, freed, count, fail_allocate, reject, synchronous;
    unsigned depth, prepares, notifications, fail_prepare;
};
static struct fake_udc fake;
static struct iq_usb_ring ring;
static struct iq_udc_adapter adapter;
static struct sdr_usb_ep ep = {0x85, 2, 512};

static struct sdr_usb_xfer *allocate(struct sdr_udc *udc)
{
    assert(udc == &fake.udc);
    if (fake.allocated == fake.fail_allocate) return NULL;
    struct fake_xfer *p = &fake.xfer[fake.allocated++];
    p->private_tail[0] = 0xa55a1234u;
    return &p->public;
}
static void release(struct sdr_udc *udc, struct sdr_usb_xfer *xfer)
{
    assert(udc == &fake.udc);
    struct fake_xfer *p = (struct fake_xfer *)xfer;
    assert(p->private_tail[0] == 0xa55a1234u);
    ++fake.freed;
}
static int enqueue(struct sdr_udc *udc, struct sdr_usb_ep *endpoint, struct sdr_usb_xfer *xfer)
{
    assert(udc == &fake.udc && endpoint == &ep && fake.depth);
    assert(xfer->uncached == 1 && xfer->zlp == 0);
    assert((uintptr_t)xfer->buf >= ring.base);
    assert(xfer->length <= ring.block_bytes && !(xfer->length & 3u));
    assert(((struct fake_xfer *)xfer)->private_tail[0] == 0xa55a1234u);
    if (fake.reject) return -2;
    if (fake.synchronous) {
        xfer->actual = xfer->length;
        xfer->complete(endpoint, xfer);
    } else {
        assert(fake.count < IQ_USB_MAX_SLOTS);
        fake.queued[fake.count++] = xfer;
    }
    return 0;
}
static void dequeue_all(struct sdr_udc *udc, struct sdr_usb_ep *endpoint)
{
    assert(udc == &fake.udc && endpoint == &ep);
    /* Deferred cancellation: no ownership returned before callbacks. */
}
static uint32_t enter(void *context)
{
    assert(context == &fake);
    return fake.depth++;
}
static void leave(void *context, uint32_t key)
{
    assert(context == &fake && fake.depth == key+1u);
    fake.depth = key;
}
static int prepare(void *context, uint32_t address, uint32_t bytes)
{
    assert(context == &fake && !fake.depth && bytes && address >= ring.base);
    ++fake.prepares;
    return !fake.fail_prepare;
}
static void notify(void *context)
{
    assert(context == &fake);
    ++fake.notifications;
}
static struct iq_udc_platform platform(void)
{
    return (struct iq_udc_platform){&fake, enter, leave, prepare, notify};
}
static void setup(unsigned slots)
{
    memset(&fake, 0, sizeof(fake));
    memset(&adapter, 0, sizeof(adapter));
    fake.fail_allocate = IQ_USB_MAX_SLOTS;
    fake.udc.ops.xfer_alloc = allocate;
    fake.udc.ops.xfer_free = release;
    fake.udc.ops.enqueue = enqueue;
    fake.udc.ops.dequeue_all = dequeue_all;
    assert(iq_usb_init(&ring, 0x80880000u, 65536u, 8192u, slots, 1));
}
static struct iq_usb_request publish(void)
{
    struct iq_usb_request request;
    assert(iq_capture_acquire(&ring, &request));
    assert(iq_capture_publish(&ring, request.token, request.bytes));
    return request;
}
static void complete(unsigned index, int status, uint32_t actual)
{
    struct sdr_usb_xfer *xfer = fake.queued[index];
    xfer->status = status;
    xfer->actual = actual;
    xfer->complete(&ep, xfer);
}

int main(void)
{
    setup(3);
    assert(iq_udc_open(&adapter, &ring, &fake.udc, &ep, platform()));
    assert(!iq_udc_open(&adapter, &ring, &fake.udc, &ep, platform()));
    struct iq_usb_request first = publish();
    struct iq_usb_request second = publish();
    assert(iq_udc_pump(&adapter, 1) == 1 && fake.count == 1);
    assert((uintptr_t)fake.queued[0]->buf == first.dma_address);
    assert(ring.slot[first.token.slot].state == IQ_USB);
    assert(!iq_udc_close(&adapter));
    assert(iq_udc_pump(&adapter, 8) == 1 && fake.count == 2);
    assert((uintptr_t)fake.queued[1]->buf == second.dma_address);
    complete(1, 0, 8192);
    assert(ring.slot[first.token.slot].state == IQ_USB);
    assert(ring.slot[second.token.slot].state == IQ_FREE);
    complete(0, 0, 8192);
    assert(ring.stats.completed_bytes == 16384 && !adapter.terminal_error);
    complete(0, 0, 8192);
    assert(adapter.callback_errors == 1 && ring.stats.completed == 2);
    assert(iq_udc_close(&adapter) && fake.freed == 3);

    setup(2);
    fake.fail_allocate = 1;
    assert(!iq_udc_open(&adapter, &ring, &fake.udc, &ep, platform()));
    assert(fake.freed == 1 && !adapter.opened);

    setup(2);
    assert(iq_udc_open(&adapter, &ring, &fake.udc, &ep, platform()));
    publish();
    fake.reject = 1;
    assert(!iq_udc_pump(&adapter, 8));
    assert(adapter.rejected == 1 && ring.stats.usb_failures == 1 && iq_usb_drained(&ring));
    assert(adapter.terminal_error && !ring.running);
    assert(iq_udc_close(&adapter));

    setup(2);
    assert(iq_udc_open(&adapter, &ring, &fake.udc, &ep, platform()));
    publish();
    fake.fail_prepare = 1;
    assert(!iq_udc_pump(&adapter, 8) && !fake.count && adapter.rejected == 1);
    assert(adapter.terminal_error && !ring.running);
    assert(iq_udc_close(&adapter));

    setup(2);
    assert(iq_udc_open(&adapter, &ring, &fake.udc, &ep, platform()));
    publish(); publish();
    assert(iq_udc_pump(&adapter, 1) == 1);
    fake.reject = 1;
    assert(!iq_udc_pump(&adapter, 1) && adapter.terminal_error);
    assert(adapter.request[0].pending && !iq_udc_close(&adapter));
    iq_udc_cancel(&adapter);
    assert(!iq_udc_close(&adapter));
    complete(0,-125,0);
    assert(iq_udc_close(&adapter) && fake.freed==2);

    setup(3);
    assert(iq_udc_open(&adapter, &ring, &fake.udc, &ep, platform()));
    publish(); publish(); publish();
    assert(iq_udc_pump(&adapter, 8) == 3);
    complete(0, -5, 17);
    assert(adapter.terminal_error && !ring.running);
    assert(!iq_udc_pump(&adapter, 8) && !iq_udc_close(&adapter));
    iq_udc_cancel(&adapter);
    assert(!iq_udc_close(&adapter));
    complete(1, -125, 0);
    assert(!iq_udc_close(&adapter));
    complete(2, -125, 0);
    assert(iq_udc_close(&adapter) && fake.freed == 3);

    setup(1);
    assert(iq_udc_open(&adapter, &ring, &fake.udc, &ep, platform()));
    fake.synchronous = 1;
    for (unsigned i = 0; i < 5000; ++i) {
        publish();
        assert(iq_udc_pump(&adapter, 4) == 1 && !fake.depth);
    }
    assert(ring.stats.completed == 5000 && !adapter.callback_errors);
    assert(iq_udc_close(&adapter));

    setup(2);
    struct iq_usb_request capturing;
    assert(iq_capture_acquire(&ring, &capturing));
    assert(!iq_udc_open(&adapter, &ring, &fake.udc, &ep, platform()));
    assert(!fake.allocated);
    puts("UDC adapter passed: buffer ownership, FIFO submission, deferred/out-of-order/synchronous completion, rejected submit, cache failure, allocation rollback, cancellation, 5000 reuses; no payload access");
    return 0;
}
