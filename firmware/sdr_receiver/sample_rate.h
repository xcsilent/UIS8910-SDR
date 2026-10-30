#ifndef UIS8910_SAMPLE_RATE_H
#define UIS8910_SAMPLE_RATE_H
#include <stdint.h>
/* Nominal rates inferred from retained one-millisecond RX geometry.
 * BW4/BW5 have equal sample counts, not necessarily equal filter passbands.
 * Capability advertisement and physical clock measurements are separate. */
static inline uint32_t sdr_nominal_sample_rate(uint32_t bw)
{
    static const uint32_t rates[]={1920000u,3840000u,7680000u,15360000u,30720000u,30720000u};
    return bw<6u?rates[bw]:0u;
}
#endif
