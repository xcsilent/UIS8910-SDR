#ifndef UIS8910_RXCAPT_RX_PRE_PROFILE_H
#define UIS8910_RXCAPT_RX_PRE_PROFILE_H
#include <stdint.h>

/* Independent CP selector experiment. RF request/config remains mode 5.
 * No rate is assigned to selector 6/7. Standard builds keep all six profiles. */
#ifdef RXCAPT_EXPERIMENTAL_BW5_PRE_SELECTOR
#if RXCAPT_EXPERIMENTAL_BW5_PRE_SELECTOR != 6 && RXCAPT_EXPERIMENTAL_BW5_PRE_SELECTOR != 7
#error experimental BW5 PRE selector must be 6 or 7
#endif
#endif

static inline uint32_t rxcapt_rx_pre_switch_profile(uint32_t rf_bandwidth,uint32_t selector)
{
    if(rf_bandwidth==5u && selector>=5u && selector<=7u)
        return (selector<<8)|8u;
    return (rf_bandwidth<<8)|8u;
}

static inline uint32_t rxcapt_rx_pre_profile(uint32_t rf_bandwidth)
{
    uint32_t selector=rf_bandwidth;
#ifdef RXCAPT_EXPERIMENTAL_BW5_PRE_SELECTOR
    if (rf_bandwidth==5u) selector=RXCAPT_EXPERIMENTAL_BW5_PRE_SELECTOR;
#endif
    return (selector<<8)|8u;
}
#endif
