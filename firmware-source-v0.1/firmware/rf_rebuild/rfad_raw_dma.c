#include "rfad_raw_dma.h"
#include "rfad_stop.h"

#define RAW_DMA_CHANNEL 0u
#define RAW_DMA_BASE UINT32_C(0x22000040)
#define RAW_DMA_CONF UINT32_C(0x22000040)
#define RAW_DMA_SADDR UINT32_C(0x22000048)
#define RAW_DMA_DADDR UINT32_C(0x2200004c)
#define RAW_DMA_COUNT UINT32_C(0x22000050)
#define RAW_DMA_COUNTP UINT32_C(0x22000054)
#define RAW_DMA_STATUS UINT32_C(0x22000058)
#define RAW_DMA_START UINT32_C(0x00000001)
#define RAW_DMA_RUN UINT32_C(0x00000001)
#define RAW_DMA_COUNT_FINISH UINT32_C(0x00200000)
#define RAW_DMA_CONF_PRESTART UINT32_C(0x00000004)
#define RAW_DMA_MAX_BLOCK_BYTES (138u * 16u * 4u)

static uint32_t rd(const struct rf_bus *b, uint32_t address) {
    return b->read(b->context, address, 4);
}

static void wr(const struct rf_bus *b, uint32_t address, uint32_t value) {
    b->write(b->context, address, value, 4);
}

enum rfad_raw_dma_result rfad_raw_dma_copy_bounded(
    const struct rf_bus *b, uint32_t table,
    uint32_t source, uint32_t destination, uint32_t bytes,
    uint32_t completion_poll_limit, uint32_t stop_poll_limit) {
    if (!b || !b->read || !b->write ||
        (source != UINT32_C(0x25010004) &&
         source != UINT32_C(0x25014004)) || (destination & 3u) || !bytes ||
        (bytes & 3u) || bytes > RAW_DMA_MAX_BLOCK_BYTES ||
        destination > UINT32_MAX - bytes || completion_poll_limit == 0 ||
        completion_poll_limit > 4096u || stop_poll_limit == 0 ||
        stop_poll_limit > 4096u || (table & 3u) ||
        table < UINT32_C(0x80000000) ||
        table > UINT32_C(0x80970000) - 48u) return RFAD_RAW_DMA_BAD_ARGUMENT;

    uint32_t channel_base = rd(b, table + 4u * RAW_DMA_CHANNEL);
    if (channel_base != RAW_DMA_BASE) return RFAD_RAW_DMA_BAD_LAYOUT;
    uint32_t status = rd(b, RAW_DMA_STATUS);
    if (status & RAW_DMA_RUN) return RFAD_RAW_DMA_CHANNEL_BUSY;
    if (status & RAW_DMA_COUNT_FINISH)
        wr(b, RAW_DMA_STATUS, RAW_DMA_COUNT_FINISH);

    /* Current CPBIN calib_axidma writes literal 4 to CONF, then byte
     * addresses/counts, then sets CONF bit 0. DWARF confirms CONF at +0x00,
     * STATUS at +0x18, and COUNT_FINISH_STA at STATUS bit 21. */
    wr(b, RAW_DMA_CONF, RAW_DMA_CONF_PRESTART);
    wr(b, RAW_DMA_SADDR, source);
    wr(b, RAW_DMA_DADDR, destination);
    wr(b, RAW_DMA_COUNT, bytes);
    wr(b, RAW_DMA_COUNTP, bytes);
    uint32_t conf = rd(b, RAW_DMA_CONF);
    wr(b, RAW_DMA_CONF, conf | RAW_DMA_START);

    uint32_t completion_seen = 0;
    for (uint32_t i = 0; i < completion_poll_limit; ++i) {
        status = rd(b, RAW_DMA_STATUS);
        if (status & RAW_DMA_COUNT_FINISH) {
            wr(b, RAW_DMA_STATUS, RAW_DMA_COUNT_FINISH);
            completion_seen = 1;
        }
        if (completion_seen && !(status & RAW_DMA_RUN)) return RFAD_RAW_DMA_OK;
    }

    enum rfad_dma_stop_result stopped = rfad_dma_stop_bounded(
        b, table, RAW_DMA_CHANNEL, 0, stop_poll_limit);
    if (stopped == RFAD_DMA_QUIET) {
        status = rd(b, RAW_DMA_STATUS);
        if (status & RAW_DMA_COUNT_FINISH)
            wr(b, RAW_DMA_STATUS, RAW_DMA_COUNT_FINISH);
        return RFAD_RAW_DMA_TIMEOUT;
    }
    if (stopped == RFAD_DMA_BAD_LAYOUT || stopped == RFAD_DMA_BAD_ARGUMENT)
        return RFAD_RAW_DMA_BAD_LAYOUT;
    return RFAD_RAW_DMA_STOP_FAILED;
}
