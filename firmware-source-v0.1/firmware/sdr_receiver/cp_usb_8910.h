#ifndef SDR_CP_USB_8910_H
#define SDR_CP_USB_8910_H
#include "cp_usb_stream.h"
#include "cp_usb_scheduler.h"

struct cp_usb_8910 {
    struct cp_usb_stream stream;
    struct cp_stream_mailbox mailbox;
    struct cp_capture_snapshot last_snapshot;
    void *wake;
    uint32_t prepared, opened, last_snapshot_ms, snapshot_misses;
    uint32_t launch_attempted, launch_result, run_error;
    uint32_t stop_requested;
    uint32_t capture_epoch,epoch_started,source_stop_seen,source_stop_seen_ms;
    uint32_t session_clock_started,session_started_ms,session_duration_ms;
    uint32_t session_lease_enabled,session_control_ms,lease_expired;
    struct cp_usb_scheduler scheduler;
#if defined(SDR_EXPERIMENTAL_FEM_OVERRIDE) && SDR_EXPERIMENTAL_FEM_OVERRIDE
    uint32_t fem_override_mode;
#endif
};
/* Zero-initialize once. prepare runs while CP is idle, before RF/CP activation.
 * Bindings are generated from the exact AP and CP module build. The outer
 * worker must exclude generic monitor writes to this mailbox during capture.
 * Original CP 7x8000-byte region must be reserved, AP read-only and exclusively
 * owned by this producer. Do not reuse the fixed AP benchmark cache callback.
 */
int cp_usb_8910_prepare(struct cp_usb_8910 *, volatile uint32_t *mailbox);
/* open is retried by the outer worker only while CP initializes (bounded by
 * that worker). It needs the newly allocated exclusive Bulk endpoint enabled.
 */
int cp_usb_8910_open(struct cp_usb_8910 *, struct sdr_udc *, struct sdr_usb_ep *, uint32_t duration_ms);
void cp_usb_8910_tick(struct cp_usb_8910 *);
void cp_usb_8910_stop(struct cp_usb_8910 *);
int cp_usb_8910_session_expired(struct cp_usb_8910 *,uint32_t now_ms);
void cp_usb_8910_wait(struct cp_usb_8910 *, uint32_t maximum_ms);
int cp_usb_8910_dispose(struct cp_usb_8910 *);
int cp_usb_8910_final_scratch_drops(struct cp_usb_8910 *,uint32_t *);
struct cp_usb_8910_launch {
    struct sdr_udc *udc;
    struct sdr_usb_ep *ep;
    volatile uint32_t *mailbox;
    uint32_t duration_ms;
    /* CP resident/control must already be loaded, activated and initialized;
     * callback submits the non-returning 0x100b asynchronously. 1 means
     * submitted, 0 guarantees NOT submitted, negative means uncertain.
     * This is control-plane integration, never a per-block CP call.
     */
    int (*start)(void *context);
    void *context;
};
/* Call from the persistent AP worker with exclusive endpoint/mailbox access.
 * Returns DRAINED, FAULT or CLOSED (pre-launch failure). Context must remain
 * alive on FAULT: pending CP/UDC ownership can outlive this call. No reset or
 * automatic retry; CP DRAINED still holds RF/CP. Use explicit restart only
 * with the matched native REARM resident; it is not modem IDLE.
 */
uint32_t cp_usb_8910_run(struct cp_usb_8910 *,const struct cp_usb_8910_launch *);
/* Only after successful drain with CP still held. Preserve the mailbox cursor,
 * reserve USB requests, then request a native full-initialization transaction.
 * No CP gateway call, mailbox clear, modem scheduler resume or chip reset. */
uint32_t cp_usb_8910_restart(struct cp_usb_8910 *,struct sdr_udc *,struct sdr_usb_ep *,
    uint32_t duration_ms,uint32_t raw_frequency,uint32_t gain_index,uint32_t channel);
uint32_t cp_usb_8910_restart_bw(struct cp_usb_8910 *,struct sdr_udc *,struct sdr_usb_ep *,
    uint32_t duration_ms,uint32_t raw_frequency,uint32_t gain_index,uint32_t channel,uint32_t bandwidth_index);
#endif
