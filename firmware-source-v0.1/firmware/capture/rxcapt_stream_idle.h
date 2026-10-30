#ifndef RXCAPT_STREAM_IDLE_H
#define RXCAPT_STREAM_IDLE_H
#include <stdint.h>
/* Call after validating ring ABI. The seventh metadata row is private scratch
 * in six-output-slot experiments; production seven-slot rings already scan it. */
static inline uint32_t rxcapt_rows_dma_idle(volatile uint32_t *state, uint32_t scratch_enabled) {
    uint32_t rows=state[2];
    if(scratch_enabled && rows==6u) rows=7u;
    for(uint32_t i=0;i<rows;i++)if(state[10u+3u*i]&3u)return 0;
    return 1;
}
#endif
