#ifndef SDR_IQ_UDC_ADAPTER_H
#define SDR_IQ_UDC_ADAPTER_H

#include "iq_usb_ring.h"
#include "udc_8910.h"
#if SDR_USB_SEGMENT_PROFILE
#include "usb_queue_observer.h"
#endif

struct iq_udc_adapter;
struct iq_udc_platform {
    void *context;
    /* Must support nesting: the native enqueue path also enters critical. */
    uint32_t (*enter)(void *);
    void (*leave)(void *, uint32_t);
    /* Establish DMA visibility, then a DMA barrier. No payload copy.
     * CP/DMA-produced buffers must NOT be cleaned from stale AP cache.
     * A fixed AP-produced test buffer can be cleaned once before streaming.
     * Return 1 only if UDC may read the address with uncached=1.
     */
    int (*prepare_tx)(void *, uint32_t address, uint32_t bytes);
    /* ISR-safe notification only; do not pump/allocate/free from here. */
    void (*notify)(void *);
};
struct iq_udc_pending {
    struct iq_udc_adapter *owner;
    struct sdr_usb_xfer *xfer;
    struct iq_token token;
    uint32_t bytes, pending;
#if SDR_USB_SEGMENT_PROFILE
    uint64_t submitted_at;
    uint32_t profiled;
    enum usb_queue_request_state queue_state;
#endif
};
struct iq_udc_adapter {
    struct iq_usb_ring *ring;
    struct sdr_udc *udc;
    struct sdr_usb_ep *ep;
    struct iq_udc_platform platform;
    uint32_t slots, opened, terminal_error, callback_errors, rejected;
#if SDR_USB_SEGMENT_PROFILE
    struct usb_queue_observer queue_observer;
#endif
    struct iq_udc_pending request[IQ_USB_MAX_SLOTS];
};

/* Zero-initialize the adapter once before its first open. Endpoint must
 * already be enabled and EXCLUSIVELY owned by this service;
 * there must be no vendor serial/diag writer or foreign request on it.
 * open/close/pump/cancel run in one worker. Ring producer calls use the same
 * platform critical section; callbacks take it internally.
 */
int iq_udc_open(struct iq_udc_adapter *, struct iq_usb_ring *, struct sdr_udc *,
                struct sdr_usb_ep *, struct iq_udc_platform);
uint32_t iq_udc_pump(struct iq_udc_adapter *, uint32_t budget);
/* Stop the capture DMA before cancel. Cancellation never fabricates completion
 * or releases a buffer while the controller can still reference it.
 */
void iq_udc_cancel(struct iq_udc_adapter *);
int iq_udc_close(struct iq_udc_adapter *);

#endif
