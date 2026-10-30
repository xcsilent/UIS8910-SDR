#ifndef UIS8910_RFAD_STOP_H
#define UIS8910_RFAD_STOP_H
#include "rfad.h"

/* These bus operations require clocks and RF-context ownership supplied by
 * the caller. They neither suspend L1 nor prevent IRQ/HISR/task rearming. */
void rfad_rxoff_parameters(const struct rf_bus *, const struct rfad_rx_context *, uint32_t slots);
void rfad_reset_memory(const struct rf_bus *, uint32_t cursor_context, uint32_t mode);
void rfad_txrx_rx_stop(const struct rf_bus *);
uint32_t rfad_dma_count(const struct rf_bus *, uint32_t table, uint32_t channel);
void rfad_dma_clear_count(const struct rf_bus *, uint32_t table, uint32_t channel);
uint32_t rfad_dma_started(const struct rf_bus *, uint32_t table, uint32_t channel);
void rfad_dma_release_bit(const struct rf_bus *, uint32_t used_flags, uint32_t channel);

enum rfad_dma_stop_result {
    RFAD_DMA_QUIET = 0,
    RFAD_DMA_TIMEOUT = 1,
    RFAD_DMA_BAD_ARGUMENT = 2,
    RFAD_DMA_BAD_LAYOUT = 3
};
/* A new bounded primitive, not a full replacement of halb_DmaStop. On success
 * it ends BEFORE hal_LpsZspDmaConstraintSet. It never releases a channel bit
 * or a power constraint. Timeout/layout failure keeps ownership with caller;
 * clearing START does not prove RUN=0, nor permission to restore/reuse RAM.
 * No COUNT reads: preserve residual COUNT unless clear_count is requested.
 * Table is version-bound by the integrating caller; pointer values are
 * checked against this CP's 12-channel layout before MMIO dereferencing. */
enum rfad_dma_stop_result rfad_dma_stop_bounded(const struct rf_bus *, uint32_t table,
    uint32_t channel, uint32_t clear_count, uint32_t poll_limit);
#endif
