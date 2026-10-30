#ifndef UIS8910_RFAD_RAW_CAPTURE_H
#define UIS8910_RFAD_RAW_CAPTURE_H

#include "rfad_raw_dma.h"

/* Hardware buffer geometry in 32-bit words. These are not measured sample
 * rates, ADC widths or a requirement to synchronize/decode a radio network. */
struct rfad_raw_rx_geometry {
    uint32_t cycle_words;
    uint32_t first_block_words;
    uint32_t other_block_words;
};

enum rfad_raw_rx_capture_state {
    RFAD_RAW_RX_CAPTURE_IDLE = 0,
    RFAD_RAW_RX_CAPTURE_RUNNING = 1,
    RFAD_RAW_RX_CAPTURE_HELD = 2,
    RFAD_RAW_RX_CAPTURE_ERROR = 3
};

enum rfad_raw_rx_capture_result {
    RFAD_RAW_RX_CAPTURE_ERROR_RESULT = -1,
    RFAD_RAW_RX_CAPTURE_CONTINUE = 0,
    RFAD_RAW_RX_CAPTURE_BLOCK_READY = 1,
    RFAD_RAW_RX_CAPTURE_HELD_RESULT = 2
};

struct rfad_raw_rx_capture {
    uint32_t destination;
    uint32_t capacity_bytes;
    uint32_t cycle_words;
    uint32_t first_block_words;
    uint32_t other_block_words;
    uint32_t copied_words;
    uint32_t symbol_index;
    enum rfad_raw_rx_capture_state state;
};

struct rfad_raw_rx_block {
    uint32_t source;
    uint32_t destination;
    uint32_t bytes;
    uint32_t symbol_index;
};

/* Prepare the digital RX block using the shipped calibration RX register
 * sequence, with timing mode 0. The caller owns RF/TXRX and supplies clocks,
 * calibration, analog RX enable and DMA separately. No L1/FCP/decoder calls.
 * Returns 0, or -1 before bus writes for an invalid request. */
int rfad_raw_rx_prepare(const struct rf_bus *, uint32_t bandwidth_index,
                        struct rfad_raw_rx_geometry *);

/* Prepare the same digital RX profile and assert RX_TRACE_EN (bit 7), which
 * routes pre-demod RX data to the TXRX trace window. This still does not prove
 * the trace tap is raw ADC or start the analog RF/timebase. */
int rfad_raw_rx_prepare_capture(const struct rf_bus *, uint32_t bandwidth_index,
                                struct rfad_raw_rx_geometry *);

/* Finite normal-CP sink planner. Call next() once for each qualified RX_OFDM
 * event, copy the returned block, then commit() the successful copy. It holds
 * after the 14-symbol cycle and never wraps or overwrites the destination.
 * This software state machine does not register an IRQ or launch a DMA.
 * Caller serializes these calls and supplies an exclusively owned RAM range;
 * begin() cannot verify the target address mapping or other writers. */
int rfad_raw_rx_capture_begin(struct rfad_raw_rx_capture *,
                              uint32_t destination, uint32_t capacity_bytes,
                              const struct rfad_raw_rx_geometry *);
int rfad_raw_rx_capture_next(const struct rfad_raw_rx_capture *,
                             struct rfad_raw_rx_block *);
/* Call once after a qualified RX data event. Performs one bounded DMA copy,
 * commits only on success, and moves the planner to ERROR on DMA failure.
 * dma_result is written only when a copy is attempted. The caller still owns
 * event qualification, channel-0 exclusivity and timing. */
enum rfad_raw_rx_capture_result rfad_raw_rx_capture_copy_event(
    struct rfad_raw_rx_capture *, const struct rf_bus *, uint32_t dma_channel_table,
    uint32_t completion_poll_limit, uint32_t stop_poll_limit,
    enum rfad_raw_dma_result *dma_result);
int rfad_raw_rx_capture_commit(struct rfad_raw_rx_capture *,
                               const struct rfad_raw_rx_block *,
                               int copy_completed);

#endif
