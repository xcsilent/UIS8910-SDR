#ifndef SDR_CP_USB_STREAM_H
#define SDR_CP_USB_STREAM_H
#include "cp_capture_bridge.h"
#include "cp_stream_mailbox.h"
#include "iq_udc_adapter.h"

enum cp_usb_phase { CP_USB_CLOSED, CP_USB_RUNNING, CP_USB_STOPPING, CP_USB_DRAINED, CP_USB_FAULT, CP_USB_PREPARED };
struct cp_capture_snapshot {
    uint32_t generation, phase, error, published, released, flags, dma_idle;
};
struct cp_usb_stream {
    struct iq_usb_ring ring;
    struct cp_capture_bridge bridge;
    struct iq_udc_adapter usb;
    struct cp_stream_mailbox *mailbox;
    uint32_t phase, error, stop_requested, stop_accepted, cancelled, cp_stopped;
    uint32_t started_ms, duration_ms, stop_started_ms, commands;
};
/* Own one fresh CP capture epoch, after its producer has initialized metadata.
 * RF init and CP module activation are performed by the outer service; this
 * worker connects that producer to UDC. A DRAINED CP still owns the modem:
 * it is not a reusable RF IDLE and cannot be restarted by resetting this C
 * structure. Serialize open/stop/tick with the adapter critical section.
 */
int cp_usb_stream_open(struct cp_usb_stream *, struct cp_stream_mailbox *,
    struct sdr_udc *, struct sdr_usb_ep *, struct iq_udc_platform,
    struct cp_capture_snapshot initial, uint32_t now_ms, uint32_t duration_ms);
/* Reserve all seven UDC requests BEFORE starting RF; begin never allocates.
 * Only unprepare before launch has been submitted. Once CP may have started,
 * preserve ownership on timeout and use stop/drain or explicit recovery.
 */
int cp_usb_stream_prepare(struct cp_usb_stream *, struct cp_stream_mailbox *,
    struct sdr_udc *, struct sdr_usb_ep *, struct iq_udc_platform, uint32_t duration_ms);
int cp_usb_stream_begin(struct cp_usb_stream *, struct cp_capture_snapshot, uint32_t now_ms);
int cp_usb_stream_unprepare(struct cp_usb_stream *);
void cp_usb_stream_stop(struct cp_usb_stream *);
/* End transmission after a platform error without inventing CP stop or
 * returning any outstanding DMA ownership. Continue tick for safe cleanup.
 */
void cp_usb_stream_abort(struct cp_usb_stream *, uint32_t error);
void cp_usb_stream_tick(struct cp_usb_stream *, const struct cp_capture_snapshot *, uint32_t now_ms);
/* Read only metadata. Normal RUNNING snapshots touch two cache lines (CP
 * progress/header), not seven slot rows or IQ. Full slot state is fetched
 * only to confirm a published STOP has no DMA owners. Return 0 on a torn or
 * stale snapshot; retry on a future worker tick, never spin here.
 */
int cp_capture_snapshot_read(volatile const uint32_t *progress,
    volatile const uint32_t *exported, uint32_t generation,
    struct cp_mailbox_cache cache, struct cp_capture_snapshot *out);
/* Only for a stopped six-slot scratch producer; count is whole discarded
 * pairs, not an exact count of lost RF samples. */
int cp_capture_final_scratch_drops(volatile const uint32_t *progress,
    volatile const uint32_t *exported,uint32_t generation,
    struct cp_mailbox_cache cache,uint32_t *drops);
#endif
