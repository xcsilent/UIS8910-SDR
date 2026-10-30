#include "rfad_raw_capture.h"

int rfad_raw_rx_prepare(const struct rf_bus *b, uint32_t bandwidth_index,
                        struct rfad_raw_rx_geometry *geometry) {
    if (!b || !b->write || !geometry || bandwidth_index >= 6u) return -1;
    uint32_t scale = bandwidth_index < 4u ? 1u << bandwidth_index : 16u;
    geometry->cycle_words = 1920u * scale;
    geometry->first_block_words = 138u * scale;
    geometry->other_block_words = 137u * scale;
    b->write(b->context, UINT32_C(0x25000038), (bandwidth_index << 8) | 8u, 4);
    b->write(b->context, UINT32_C(0x25000010), 1u, 4);
    /* GLB_RXEN | RX_RSSI_EN. RX_DLFFT_EN and RX_IDDET_EN stay clear in this
     * register; independent FFT/decoder blocks are not controlled here. */
    b->write(b->context, UINT32_C(0x25000020), 3u, 4);
    b->write(b->context, UINT32_C(0x25000014), 0u, 4);
    return 0;
}

int rfad_raw_rx_prepare_capture(const struct rf_bus *b, uint32_t bandwidth_index,
                                struct rfad_raw_rx_geometry *geometry) {
    if (rfad_raw_rx_prepare(b, bandwidth_index, geometry) != 0) return -1;
    /* The shipped trace helper sets RX_CFG.RX_TRACE_EN by ORing bit 7. The
     * direct profile uses only GLB_RXEN and RSSI, so its trace-enabled value is
     * 0x83; DLFFT and IDDET remain disabled in this register. */
    b->write(b->context, UINT32_C(0x25000020), UINT32_C(0x83), 4);
    return 0;
}

int rfad_raw_rx_capture_begin(struct rfad_raw_rx_capture *capture,
                              uint32_t destination, uint32_t capacity_bytes,
                              const struct rfad_raw_rx_geometry *geometry) {
    if (!capture || !geometry || (destination & 3u) || !geometry->cycle_words ||
        !geometry->first_block_words || !geometry->other_block_words ||
        geometry->cycle_words > UINT32_MAX / 4u) return -1;
    uint32_t required_bytes = geometry->cycle_words * 4u;
    if (geometry->first_block_words > UINT32_MAX / 2u) return -1;
    uint32_t first_words = geometry->first_block_words * 2u;
    if (geometry->other_block_words > (UINT32_MAX - first_words) / 12u) return -1;
    uint32_t described_words = first_words + geometry->other_block_words * 12u;
    if (described_words != geometry->cycle_words || capacity_bytes < required_bytes ||
        destination > UINT32_MAX - required_bytes) return -1;
    capture->destination = destination;
    capture->capacity_bytes = capacity_bytes;
    capture->cycle_words = geometry->cycle_words;
    capture->first_block_words = geometry->first_block_words;
    capture->other_block_words = geometry->other_block_words;
    capture->copied_words = 0;
    capture->symbol_index = 0;
    capture->state = RFAD_RAW_RX_CAPTURE_RUNNING;
    return 0;
}

int rfad_raw_rx_capture_next(const struct rfad_raw_rx_capture *capture,
                             struct rfad_raw_rx_block *block) {
    if (!capture || !block) return RFAD_RAW_RX_CAPTURE_ERROR_RESULT;
    if (capture->state == RFAD_RAW_RX_CAPTURE_HELD)
        return RFAD_RAW_RX_CAPTURE_HELD_RESULT;
    if (capture->state != RFAD_RAW_RX_CAPTURE_RUNNING || capture->symbol_index >= 14u)
        return RFAD_RAW_RX_CAPTURE_ERROR_RESULT;
    uint32_t index = capture->symbol_index;
    uint32_t words = (index == 0u || index == 7u) ?
                     capture->first_block_words : capture->other_block_words;
    if (capture->copied_words > capture->cycle_words ||
        words > capture->cycle_words - capture->copied_words || words > UINT32_MAX / 4u)
        return RFAD_RAW_RX_CAPTURE_ERROR_RESULT;
    uint32_t offset = capture->copied_words * 4u;
    uint32_t bytes = words * 4u;
    if (offset > capture->capacity_bytes || bytes > capture->capacity_bytes - offset ||
        capture->destination > UINT32_MAX - offset ||
        capture->destination + offset > UINT32_MAX - bytes)
        return RFAD_RAW_RX_CAPTURE_ERROR_RESULT;
    block->source = (index & 1u) ? UINT32_C(0x25014004) : UINT32_C(0x25010004);
    block->destination = capture->destination + offset;
    block->bytes = bytes;
    block->symbol_index = index;
    return RFAD_RAW_RX_CAPTURE_BLOCK_READY;
}

enum rfad_raw_rx_capture_result rfad_raw_rx_capture_copy_event(
    struct rfad_raw_rx_capture *capture, const struct rf_bus *bus,
    uint32_t table, uint32_t completion_poll_limit, uint32_t stop_poll_limit,
    enum rfad_raw_dma_result *dma_result) {
    struct rfad_raw_rx_block block;
    int ready = rfad_raw_rx_capture_next(capture, &block);
    if (ready != RFAD_RAW_RX_CAPTURE_BLOCK_READY) return ready;

    enum rfad_raw_dma_result copied = rfad_raw_dma_copy_bounded(
        bus, table, block.source, block.destination, block.bytes,
        completion_poll_limit, stop_poll_limit);
    if (dma_result) *dma_result = copied;
    if (copied != RFAD_RAW_DMA_OK) {
        capture->state = RFAD_RAW_RX_CAPTURE_ERROR;
        return RFAD_RAW_RX_CAPTURE_ERROR_RESULT;
    }
    return rfad_raw_rx_capture_commit(capture, &block, 1);
}

int rfad_raw_rx_capture_commit(struct rfad_raw_rx_capture *capture,
                               const struct rfad_raw_rx_block *block,
                               int copy_completed) {
    struct rfad_raw_rx_block expected;
    if (!capture || !block ||
        rfad_raw_rx_capture_next(capture, &expected) != RFAD_RAW_RX_CAPTURE_BLOCK_READY ||
        block->source != expected.source || block->destination != expected.destination ||
        block->bytes != expected.bytes || block->symbol_index != expected.symbol_index) {
        if (capture) capture->state = RFAD_RAW_RX_CAPTURE_ERROR;
        return RFAD_RAW_RX_CAPTURE_ERROR_RESULT;
    }
    if (!copy_completed) {
        capture->state = RFAD_RAW_RX_CAPTURE_ERROR;
        return RFAD_RAW_RX_CAPTURE_ERROR_RESULT;
    }
    capture->copied_words += block->bytes / 4u;
    capture->symbol_index++;
    if (capture->symbol_index == 14u) {
        if (capture->copied_words != capture->cycle_words) {
            capture->state = RFAD_RAW_RX_CAPTURE_ERROR;
            return RFAD_RAW_RX_CAPTURE_ERROR_RESULT;
        }
        capture->state = RFAD_RAW_RX_CAPTURE_HELD;
        return RFAD_RAW_RX_CAPTURE_HELD_RESULT;
    }
    return RFAD_RAW_RX_CAPTURE_CONTINUE;
}
