#ifndef RXCAPT_LOSSY_PAIR_H
#define RXCAPT_LOSSY_PAIR_H
#include <stdint.h>

/* Experimental metadata primitive, not linked into the deployed producer.
 * Caller serializes with CP mailbox, owns both DMA channels and rearms them
 * only together after both completed. scratch is a physical slot outside the
 * AP-visible output ring. No payload accesses or cache maintenance here. */
struct rxcapt_lossy_pair { uint32_t slot, completed, dropped_pairs, active; };
enum { RX_LOSSY_ERROR=0, RX_LOSSY_ARM=1, RX_LOSSY_WAIT=2, RX_LOSSY_STOP=3 };
/* Adopt the first pair already reserved by rxcapt_stream_state_init and
 * started by the vendor arm routine. Must be called before either completes. */
uint32_t rxcapt_lossy_adopt_initial(volatile uint32_t *ring, struct rxcapt_lossy_pair *pair);
uint32_t rxcapt_lossy_begin(volatile uint32_t *ring, struct rxcapt_lossy_pair *pair,
                            uint32_t scratch_slot, uint32_t *slot);
uint32_t rxcapt_lossy_complete(volatile uint32_t *ring, struct rxcapt_lossy_pair *pair,
                               uint32_t channel);
/* Private scratch DMA is absent from the shared ring's row flags. A caller
 * must use this combined gate, never ring-only dma_idle, before teardown. */
uint32_t rxcapt_lossy_dma_idle(volatile uint32_t *ring, const struct rxcapt_lossy_pair *pair);
/* Keep both reservations on any arm failure until physical teardown succeeds. */
uint32_t rxcapt_lossy_arm_reserved(const struct rxcapt_lossy_pair *pair,
    uint32_t data_channel,uint32_t head_channel,
    uint32_t (*rearm)(uint32_t,uint32_t,uint32_t));
/* A STOP may meet a half-completed pair. Bound software waiting independently
 * of the renewable command cursor; expiry requests physical teardown, never
 * clears ownership. This is a poll budget, not a wall-clock guarantee. */
#define RX_LOSSY_STOP_POLLS 250000u
static inline uint32_t rxcapt_lossy_stop_expired(uint32_t stop, uint32_t *polls) {
    if (!stop) { *polls=0u; return 0u; }
    if (*polls<RX_LOSSY_STOP_POLLS) ++*polls;
    return *polls>=RX_LOSSY_STOP_POLLS;
}
#endif
