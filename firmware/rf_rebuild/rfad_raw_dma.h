#ifndef UIS8910_RFAD_RAW_DMA_H
#define UIS8910_RFAD_RAW_DMA_H

#include "rf_bus.h"

enum rfad_raw_dma_result {
    RFAD_RAW_DMA_OK = 0,
    RFAD_RAW_DMA_TIMEOUT = 1,
    RFAD_RAW_DMA_CHANNEL_BUSY = 2,
    RFAD_RAW_DMA_BAD_ARGUMENT = 3,
    RFAD_RAW_DMA_BAD_LAYOUT = 4,
    RFAD_RAW_DMA_STOP_FAILED = 5
};

/* Copy one TXRX RX ping/pang block to a caller-owned CP RAM buffer through
 * the vendor calibration DMA sequence. The caller must exclusively own
 * channel 0 and invoke this only in a CP context where these MMIO accesses
 * are valid. Poll limits count status reads, not elapsed time. This helper
 * performs no cache maintenance; the caller owns the buffer's cache policy.
 * A timeout never reports the destination as complete. */
enum rfad_raw_dma_result rfad_raw_dma_copy_bounded(
    const struct rf_bus *, uint32_t dma_channel_table,
    uint32_t source, uint32_t destination, uint32_t bytes,
    uint32_t completion_poll_limit, uint32_t stop_poll_limit);

#endif
