#ifndef UIS8910_RFAD_OFF_IMMEDIATE_H
#define UIS8910_RFAD_OFF_IMMEDIATE_H
#include "rfad_spi.h"

struct rfad_off_immediate_context {
    uint32_t info,rx_info,tx_info,rfnv,cursor;
};
/* Reconstructs the five immediate RX/TX/FEM-off helpers (six SPI words).
 * TX is only turned OFF. No receive/transmit ON command is generated.
 * Caller owns RFAD/timer and supplies initialized, readable calibration and
 * RF context. This does not clear queued RFAD events, stop DMA, reset L1
 * bookkeeping or prove physical RF shutdown. Combine with those explicitly.
 * completed counts fully finished SPI transactions. A later failing command
 * may already have been submitted: retain ownership on any error.
 * Invalid parameters leave completed unchanged, before RF writes. */
enum rfad_frame_time_result rfad_off_immediate_bounded(
    const struct rf_bus *,const struct rfad_off_immediate_context *,
    uint32_t card,uint32_t poll_limit,uint32_t *completed);
#endif
