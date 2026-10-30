#define RXCAPT_MULTI_PROFILE 1
#include "rxcapt_profile.h"

/* Bounded, manual-route experiment. Defaults retain the delivered envelope. */
#if defined(RXCAPT_EXPERIMENTAL_B3_MIN_RAW) && (RXCAPT_EXPERIMENTAL_B3_MIN_RAW < 16500000u || RXCAPT_EXPERIMENTAL_B3_MIN_RAW >= 17100000u)
#error B3 experimental floor must be in [1650,1710) MHz
#endif

/* One implementation per image; CP control links the same implementation.
 * Newly added routes use fixed middle anchors so NV calibration selection
 * remains independent from the requested raw center. B41 anchor40640 maps
 * to2595MHz for all three verified native NV table variants. */
struct profile { uint16_t band,low,high; uint32_t anchor_raw,minimum_raw,maximum_raw; };
static const struct profile profiles[]={
    {1,300,300,21400000u,21100000u,21699000u},
    /* Experimental envelopes include native UL candidates/adjacent paths.
     * AP clamps initialization to a valid DL anchor; raw tuning is separate.
     * No reception claim follows from these software bounds. */
    /* Request envelope includes v31/v32 reference points down to1375MHz;
     * it is not a measured continuous physical receive interval. */
    {3,1200,1949,18050000u,13750000u,19200000u},
    /* Experimental request floor; sub-700 MHz reception is unverified. */
    {5,2400,2649,8690000u,5000000u,9250000u},
    {7,3100,3100,26550000u,26200000u,26899000u},
    {8,3450,3799,9250000u,8800000u,10000000u},
    {18,5925,5925,8675000u,8600000u,8749000u},
    {19,6075,6075,8825000u,8750000u,8899000u},
    {26,8865,8865,8765000u,8590000u,8939000u},
    {34,36275,36275,20175000u,20100000u,20249000u},
    {38,38000,38000,25950000u,25700000u,26199000u},
    {39,38450,38450,19000000u,18800000u,19199000u},
    {40,38950,38950,23300000u,18843750u,27906250u},
    {41,40640,40640,25950000u,24960000u,26899000u}
};
#ifndef RXCAPT_UNRESTRICTED_FREQUENCY
static uint32_t minimum_raw(const struct profile *p)
{
#ifdef RXCAPT_EXPERIMENTAL_B3_MIN_RAW
    if(p->band==3) return RXCAPT_EXPERIMENTAL_B3_MIN_RAW;
#endif
    return p->minimum_raw;
}
#endif
static const struct profile *find(uint32_t channel)
{
    for(unsigned i=0;i<sizeof(profiles)/sizeof(profiles[0]);++i)
        if(channel>=profiles[i].low && channel<=profiles[i].high) return profiles+i;
    return 0;
}
uint32_t terminal_profile_anchor(uint32_t channel)
{
    const struct profile *p=find(channel);
    return p?p->anchor_raw+(channel-p->low)*1000u:0;
}
int terminal_profile_channel_valid(uint32_t channel) { return find(channel)!=0; }
static uint32_t profile_channel(uint32_t band,uint32_t hz,int automatic)
{
    if(!hz || hz%100u) return 0;
    uint32_t raw=hz/100u;
    for(unsigned i=0;i<sizeof(profiles)/sizeof(profiles[0]);++i) {
        const struct profile *p=profiles+i;
        if(p->band!=band) continue;
        if(automatic && (raw<p->minimum_raw || raw>p->maximum_raw)) continue;
#ifndef RXCAPT_UNRESTRICTED_FREQUENCY
        if(!automatic && (raw<minimum_raw(p) || raw>p->maximum_raw)) continue;
#endif
        if(p->low==p->high || raw<p->anchor_raw) return p->low;
        uint32_t channel=p->low+(raw-p->anchor_raw)/1000u;
        return channel>p->high?p->high:channel;
    }
    return 0;
}
uint32_t terminal_profile_channel(uint32_t band,uint32_t hz)
{ return profile_channel(band,hz,0); }
/* Auto always uses the shared table, even in a manual unrestricted build. */
uint32_t terminal_profile_auto_channel(uint32_t band,uint32_t hz)
{ return profile_channel(band,hz,1); }
int terminal_profile_raw_valid(uint32_t channel,uint32_t raw)
{
    const struct profile *p=find(channel);
#ifdef RXCAPT_UNRESTRICTED_FREQUENCY
    /* zero retains native channel mode; other values must fit uint32 Hz. */
    return p && raw<=42949672u;
#else
    return p && (!raw || (raw>=minimum_raw(p) && raw<=p->maximum_raw));
#endif
}
