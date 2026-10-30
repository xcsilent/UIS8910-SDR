#ifndef SDR_RF_PROFILE_H
#define SDR_RF_PROFILE_H
#define RXCAPT_MULTI_PROFILE 1
#include "../capture/rxcapt_profile.h"
/* The requested route remains explicit even when future envelopes overlap. */
static inline uint32_t sdr_rf_channel(uint32_t band,uint32_t hz)
{
    return terminal_profile_channel(band,hz);
}
#endif
