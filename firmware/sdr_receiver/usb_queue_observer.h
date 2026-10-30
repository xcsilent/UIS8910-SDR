#ifndef SDR_USB_QUEUE_OBSERVER_H
#define SDR_USB_QUEUE_OBSERVER_H
#include <stdint.h>

/* Caller serializes all operations. This is software ownership, not a direct
 * hardware queue/idle register. A synchronous completion is deliberately not
 * classified as starvation because enqueue has not yet returned. */
enum usb_queue_request_state { USB_Q_IDLE, USB_Q_SUBMITTING, USB_Q_ACCEPTED, USB_Q_SYNC_DONE };
struct usb_queue_observer {
    uint32_t accepted, completions, empty_completions, synchronous, rejected, cancelled;
    uint32_t gap_count, gap_max_us, gap_open;
    uint64_t gap_started_us, gap_total_us;
};
static inline void usb_queue_begin(enum usb_queue_request_state *s) { *s=USB_Q_SUBMITTING; }
static inline void usb_queue_complete(struct usb_queue_observer *q,enum usb_queue_request_state *s,int successful,int stopping,uint64_t now)
{
    if(*s==USB_Q_SUBMITTING) { ++q->synchronous; *s=USB_Q_SYNC_DONE; return; }
    if(*s!=USB_Q_ACCEPTED) return;
    --q->accepted; *s=USB_Q_IDLE;
    if(stopping || !successful) { ++q->cancelled; q->gap_open=0; return; }
    ++q->completions;
    if(!q->accepted) { ++q->empty_completions; q->gap_started_us=now; q->gap_open=1; }
}
static inline void usb_queue_submit_result(struct usb_queue_observer *q,enum usb_queue_request_state *s,int accepted,uint64_t now)
{
    if(*s==USB_Q_SYNC_DONE) {
        *s=USB_Q_IDLE;
        /* Submission completed before return; do not carry an earlier empty
         * interval across this submission. Its timing is not classified. */
        q->gap_open=0;
        if(!accepted)++q->rejected;
        return;
    }
    if(*s!=USB_Q_SUBMITTING) return;
    if(accepted) {
        *s=USB_Q_ACCEPTED; ++q->accepted;
        if(q->gap_open) {
            uint64_t gap=now-q->gap_started_us; ++q->gap_count; q->gap_total_us+=gap;
            if(gap>q->gap_max_us)q->gap_max_us=gap>UINT32_MAX?UINT32_MAX:(uint32_t)gap;
            q->gap_open=0;
        }
    } else { *s=USB_Q_IDLE; ++q->rejected; q->gap_open=0; }
}
#endif
