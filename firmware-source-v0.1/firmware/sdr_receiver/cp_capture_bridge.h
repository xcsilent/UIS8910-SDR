#ifndef SDR_CP_CAPTURE_BRIDGE_H
#define SDR_CP_CAPTURE_BRIDGE_H
#include "iq_usb_ring.h"

/* AP-side adapter for the optional CP batch service. The control worker issues
 * CP operation 11 at claimed, then commits its returned exclusive end.
 * After UDC callbacks return ownership, operation 12 releases the completed
 * prefix. Address mapping is the existing seven 8000-byte CP DMA slots.
 *
 * All calls and UDC ring operations share the platform critical section.
 * No CP mailbox addresses/cache policy are guessed here; the platform must
 * bind a new service build to the NEW AP mailbox address before enabling it.
 */
struct cp_capture_bridge {
    struct iq_usb_ring *ring;
    uint32_t generation, claimed, released, pending_release, terminal_error;
    uint32_t claim_batches, release_batches;
};
int cp_capture_bridge_init(struct cp_capture_bridge *, struct iq_usb_ring *, uint32_t generation);
uint32_t cp_capture_claim_credit(const struct cp_capture_bridge *);
int cp_capture_claim_commit(struct cp_capture_bridge *, uint32_t generation, uint32_t first, uint32_t end);
/* begin returns exclusive CP release end, or zero if no prefix is complete.
 * It never frees CP memory itself. Commit only on CP operation-12 success.
 */
uint32_t cp_capture_release_begin(struct cp_capture_bridge *);
int cp_capture_release_commit(struct cp_capture_bridge *, uint32_t generation, uint32_t end);
/* Commit a matched combined-exchange reply. release_end must be the exact
 * pending completed prefix (or current released when none). Validate both
 * halves before mutation; no partial release on an invalid claim reply.
 * Caller holds the same critical section as UDC callbacks. */
int cp_capture_exchange_commit(struct cp_capture_bridge *,uint32_t generation,uint32_t release_end,uint32_t claim_end);
void cp_capture_bridge_fail(struct cp_capture_bridge *);
#endif
