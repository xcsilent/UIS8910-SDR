#ifndef RXCAPT_PROFILE_H
#define RXCAPT_PROFILE_H
#include <stdint.h>

/* The channel selects native initialization/calibration. A raw center is
 * independent of that anchor. These are software experiment envelopes,
 * not claims of contiguous reception or physical tuning limits. */
#if defined(RXCAPT_MULTI_PROFILE) && RXCAPT_MULTI_PROFILE
uint32_t terminal_profile_anchor(uint32_t channel);
uint32_t terminal_profile_channel(uint32_t band,uint32_t hz);
uint32_t terminal_profile_auto_channel(uint32_t band,uint32_t hz);
int terminal_profile_channel_valid(uint32_t channel);
int terminal_profile_raw_valid(uint32_t channel,uint32_t raw);
#else
static inline uint32_t terminal_profile_anchor(uint32_t channel)
{
    return 8690000u+(channel-2400u)*1000u;
}
static inline int terminal_profile_channel_valid(uint32_t channel)
{
    return channel>=2400u && channel<=2649u;
}
static inline int terminal_profile_raw_valid(uint32_t channel,uint32_t raw)
{
    if(!terminal_profile_channel_valid(channel)) return 0;
    if(!raw) return 1; /* ordinary channel mode */
    return raw>=8690000u && raw<=8939000u;
}
#endif
#endif
