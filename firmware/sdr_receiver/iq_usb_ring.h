#ifndef SDR_IQ_USB_RING_H
#define SDR_IQ_USB_RING_H

#include <stdint.h>

#define IQ_USB_MAX_SLOTS 64u

/* Control metadata only. No fields in these structures are sent with IQ.
 * Serialize all calls in the adapter, including DMA/UDC completion events.
 * The adapter owns cache maintenance, address translation and DMA barriers.
 * Never initialize a live ring: stop and drain both DMA engines first.
 */
enum iq_slot_state { IQ_FREE, IQ_CAPTURING, IQ_READY, IQ_USB };

struct iq_token { uint32_t generation, sequence, slot; };
struct iq_usb_request {
    struct iq_token token;
    uint32_t dma_address, bytes;
};
struct iq_slot { uint32_t state, sequence, bytes; };
struct iq_usb_stats {
    uint32_t acquired, overrun_drops, submitted, completed, usb_failures;
    uint32_t stop_drops, stale_events, sequence_exhausted;
    uint64_t completed_bytes;
};
struct iq_usb_ring {
    uint32_t base, block_bytes, slots, generation, next_sequence, running;
    struct iq_usb_stats stats;
    struct iq_slot slot[IQ_USB_MAX_SLOTS];
};

/* region_bytes must describe an independently reserved, DMA-visible window.
 * Four-byte alignment preserves whole interleaved 16+16-bit complex samples.
 * Return 1 on success, 0 on invalid input / no available work.
 */
int iq_usb_init(struct iq_usb_ring *r, uint32_t base, uint32_t region_bytes,
                uint32_t block_bytes, uint32_t slots, uint32_t generation);
int iq_capture_acquire(struct iq_usb_ring *r, struct iq_usb_request *out);
int iq_capture_publish(struct iq_usb_ring *r, struct iq_token token, uint32_t bytes);
int iq_capture_abort(struct iq_usb_ring *r, struct iq_token token);
int iq_usb_take(struct iq_usb_ring *r, struct iq_usb_request *out);
/* Call only after UDC has stopped referencing the buffer. A rejected submit
 * may be completed immediately with success=0. No retry is scheduled.
 */
int iq_usb_complete(struct iq_usb_ring *r, struct iq_token token, int success);
void iq_usb_stop(struct iq_usb_ring *r);
int iq_usb_drained(const struct iq_usb_ring *r);

#endif
