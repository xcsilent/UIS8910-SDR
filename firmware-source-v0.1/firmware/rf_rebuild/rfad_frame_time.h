#ifndef UIS8910_RFAD_FRAME_TIME_H
#define UIS8910_RFAD_FRAME_TIME_H
#include "rf_bus.h"

struct rfad_frame_time {
    uint16_t cycle,ssfn,sfn,asfn,offset;
};
enum rfad_frame_time_result {
    RFAD_FRAME_TIME_OK=0,
    RFAD_FRAME_TIME_TIMEOUT=1,
    RFAD_FRAME_TIME_BAD_ARGUMENT=2,
    RFAD_FRAME_TIME_BAD_CLOCK=3
};
/* Caller owns the RF timer and supplies its clock/power precondition. Card
 * selects the two timer banks explicitly, without the vendor global flag.
 * Raw units only: these functions do not establish a physical time unit.
 * Every loop is bounded. No MMIO write, RF request, DMA or OS call occurs. */
enum rfad_frame_time_result rfad_read_frame_time_bounded(
    const struct rf_bus *,uint32_t card,uint32_t poll_limit,struct rfad_frame_time *);
enum rfad_frame_time_result rfad_wait_frame_ticks_bounded(
    const struct rf_bus *,uint32_t card,uint32_t ticks,uint32_t poll_limit);
#endif
