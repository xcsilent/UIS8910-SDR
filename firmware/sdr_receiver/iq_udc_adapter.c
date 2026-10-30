#include "iq_udc_adapter.h"
#if SDR_USB_SEGMENT_PROFILE
#include "usb_segment_profile.h"
#endif

static void done(struct sdr_usb_ep *ep, struct sdr_usb_xfer *xfer)
{
    struct iq_udc_pending *p = xfer->param;
    struct iq_udc_adapter *a = p->owner;
    uint32_t key = a->platform.enter(a->platform.context);
    if (!a->opened || ep != a->ep || !p->pending || p->xfer != xfer) {
        ++a->callback_errors;
    } else {
#if SDR_USB_SEGMENT_PROFILE
        if(p->profiled) {
            uint64_t now=sdr_usb_profile_clock();
            usb_segment_profile_record(USB_PROFILE_COMPLETE,p->submitted_at,now);
            uint32_t empty_before=a->queue_observer.empty_completions;
            usb_queue_complete(&a->queue_observer,&p->queue_state,
                xfer->status==0 && xfer->actual==p->bytes,!a->ring->running,now);
            if(a->queue_observer.empty_completions!=empty_before)usb_refill_begin(now);
            else if(!a->ring->running || xfer->status || xfer->actual!=p->bytes)
                usb_refill_end(0,now);
        }
        p->profiled=0;
#endif
        int success = xfer->status == 0 && xfer->actual == p->bytes;
        p->pending = 0;
        iq_usb_complete(a->ring, p->token, success);
        if (!success) {
            /* A failed/partial transfer can invalidate byte alignment. End the
             * epoch; the worker stops capture and cancels remaining requests.
             */
            a->terminal_error = 1;
            iq_usb_stop(a->ring);
        }
    }
    a->platform.leave(a->platform.context, key);
    a->platform.notify(a->platform.context);
}

int iq_udc_open(struct iq_udc_adapter *a, struct iq_usb_ring *ring,
                struct sdr_udc *udc, struct sdr_usb_ep *ep,
                struct iq_udc_platform platform)
{
    if (!a || a->opened || !ring || !udc || !ep || !platform.enter || !platform.leave ||
        !platform.prepare_tx || !platform.notify || !udc->ops.xfer_alloc ||
        !udc->ops.xfer_free || !udc->ops.enqueue || !udc->ops.dequeue_all ||
        !(ep->address & 0x80u) || ep->mps != 512u || !ring->slots ||
        ring->slots > IQ_USB_MAX_SLOTS || ring->block_bytes > 65536u)
        return 0;
    for (uint32_t i = 0; i < ring->slots; ++i)
        if (ring->slot[i].state != IQ_FREE) return 0;
    *a = (struct iq_udc_adapter){0};
    a->ring = ring;
    a->udc = udc;
    a->ep = ep;
    a->platform = platform;
    a->slots = ring->slots;
    for (uint32_t i = 0; i < a->slots; ++i) {
        struct iq_udc_pending *p = &a->request[i];
        p->owner = a;
        p->xfer = udc->ops.xfer_alloc(udc);
        if (!p->xfer) {
            while (i) udc->ops.xfer_free(udc, a->request[--i].xfer);
            a->slots = 0;
            return 0;
        }
        /* Only initialize the public prefix. The allocated request has private
         * queue links/flags beyond it, initialized by the UDC allocator.
         */
        *p->xfer = (struct sdr_usb_xfer){0};
        p->xfer->param = p;
        p->xfer->complete = done;
        p->xfer->uncached = 1;
    }
    a->opened = 1;
    return 1;
}

uint32_t iq_udc_pump(struct iq_udc_adapter *a, uint32_t budget)
{
    if (!a || !a->opened) return 0;
    uint32_t submitted = 0;
    while (submitted < budget) {
        struct iq_usb_request request;
        uint32_t key = a->platform.enter(a->platform.context);
        if (a->terminal_error || !iq_usb_take(a->ring, &request)) {
            a->platform.leave(a->platform.context, key);
            break;
        }
        struct iq_udc_pending *p = &a->request[request.token.slot];
        p->token = request.token;
        p->bytes = request.bytes;
        p->pending = 1;
        p->xfer->buf = (void *)(uintptr_t)request.dma_address;
        p->xfer->length = request.bytes;
        p->xfer->actual = 0;
        p->xfer->status = 0;
        a->platform.leave(a->platform.context, key);
#if SDR_USB_SEGMENT_PROFILE
        uint32_t profiling=usb_segment_profile_enabled();
        uint64_t prepare_start=profiling?sdr_usb_profile_clock():0;
#endif
        int ready = a->platform.prepare_tx(a->platform.context, request.dma_address, request.bytes);
#if SDR_USB_SEGMENT_PROFILE
        if(profiling)usb_segment_profile_record(USB_PROFILE_PREPARE,prepare_start,sdr_usb_profile_clock());
#endif
        key = a->platform.enter(a->platform.context);
#if SDR_USB_SEGMENT_PROFILE
        uint32_t enqueue_attempted=ready && !a->terminal_error;
        uint64_t enqueue_start=profiling && enqueue_attempted?sdr_usb_profile_clock():0;
        p->profiled=profiling && enqueue_attempted;p->submitted_at=enqueue_start;
        if(p->profiled)usb_queue_begin(&p->queue_state);
#endif
        int result = ready && !a->terminal_error ? a->udc->ops.enqueue(a->udc, a->ep, p->xfer) : -1;
#if SDR_USB_SEGMENT_PROFILE
        if(profiling && enqueue_attempted) {
            uint64_t now=sdr_usb_profile_clock();
            usb_segment_profile_record(USB_PROFILE_ENQUEUE,enqueue_start,now);
            usb_queue_submit_result(&a->queue_observer,&p->queue_state,result>=0,now);
            if(!a->queue_observer.gap_open)
                usb_refill_end(result>=0 && p->queue_state==USB_Q_ACCEPTED,now);
        }
#endif
        if (result < 0) {
            /* Permit synchronous completion inside enqueue without a second
             * release. A rejected submit has no outstanding controller owner.
             */
            if (p->pending) {
                p->pending = 0;
#if SDR_USB_SEGMENT_PROFILE
                p->profiled=0;
                if(profiling)usb_refill_end(0,sdr_usb_profile_clock());
#endif
                iq_usb_complete(a->ring, p->token, 0);
                ++a->rejected;
            }
            /* Cache handoff/submission failure is a transport fault. Stop the
             * epoch rather than repeatedly dropping blocks while capture runs.
             * Other queued transfers retain ownership until their callbacks. */
            a->terminal_error = 1;
            iq_usb_stop(a->ring);
            a->platform.leave(a->platform.context, key);
            break;
        }
        a->platform.leave(a->platform.context, key);
        ++submitted;
    }
    return submitted;
}

void iq_udc_cancel(struct iq_udc_adapter *a)
{
    if (!a || !a->opened) return;
    uint32_t key = a->platform.enter(a->platform.context);
    iq_usb_stop(a->ring);
#if SDR_USB_SEGMENT_PROFILE
    a->queue_observer.gap_open=0;
    if(usb_segment_profile_enabled())usb_refill_end(0,sdr_usb_profile_clock());
#endif
    a->platform.leave(a->platform.context, key);
    a->udc->ops.dequeue_all(a->udc, a->ep);
}

int iq_udc_close(struct iq_udc_adapter *a)
{
    if (!a || !a->opened) return 0;
    uint32_t key = a->platform.enter(a->platform.context);
    if (!iq_usb_drained(a->ring)) {
        a->platform.leave(a->platform.context, key);
        return 0;
    }
    for (uint32_t i = 0; i < a->slots; ++i) {
        if (a->request[i].pending) {
            a->platform.leave(a->platform.context, key);
            return 0;
        }
    }
    a->opened = 0;
#if SDR_USB_SEGMENT_PROFILE
    if(usb_segment_profile_enabled())usb_refill_end(0,sdr_usb_profile_clock());
#endif
    a->platform.leave(a->platform.context, key);
    for (uint32_t i = 0; i < a->slots; ++i)
        a->udc->ops.xfer_free(a->udc, a->request[i].xfer);
    return 1;
}
