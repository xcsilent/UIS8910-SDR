#ifndef SDR_CP_USB_SCHEDULER_H
#define SDR_CP_USB_SCHEDULER_H
#include <stdint.h>
#define CP_USB_SCHEDULER_WORDS 30u
#define CP_USB_SCHEDULER_MAX_POLLS 8u
#define CP_USB_SCHEDULER_WIDE_MIN_BW 2
struct cp_usb_scheduler {
    uint32_t wait_us,burst_us,waits,notifications,sleeps,fast_polls,exhaustions,ticks;
    uint64_t sleep_us,ack_us,queued_at,burst_at;
    uint32_t max_sleep_us,acks,max_ack_us,sleep_hist[6],ack_hist[6];
    uint32_t pending,burst_polls;
    uint32_t manual_override,bandwidth_index;
};
/* Pure policy/statistics, no memory ownership, payload access or OS calls.
 * Caller serializes access. Microsecond values are elapsed wall time, not CPU
 * cycles; ACK time is AP observation latency, not CP execution time alone. */
int cp_usb_scheduler_configure(struct cp_usb_scheduler *,uint32_t wait_us,uint32_t burst_us);
/* Automatic policy is selected at START; explicit configuration persists
 * across START/STOP and bandwidth changes until automatic is requested. */
void cp_usb_scheduler_automatic(struct cp_usb_scheduler *);
int cp_usb_scheduler_begin(struct cp_usb_scheduler *,uint32_t bandwidth_index);
void cp_usb_scheduler_reset(struct cp_usb_scheduler *);
void cp_usb_scheduler_observe(struct cp_usb_scheduler *,uint32_t pending,uint32_t completed,uint64_t now_us);
uint32_t cp_usb_scheduler_wait(struct cp_usb_scheduler *,uint32_t notification,uint32_t may_wait,uint32_t pending,uint64_t now_us);
void cp_usb_scheduler_slept(struct cp_usb_scheduler *,uint64_t elapsed_us);
void cp_usb_scheduler_words(const struct cp_usb_scheduler *,uint32_t out[CP_USB_SCHEDULER_WORDS]);
#endif
