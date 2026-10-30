#ifndef RXCAPT_PROFILE_NV_H
#define RXCAPT_PROFILE_NV_H
#if defined(RXCAPT_MULTI_PROFILE) && RXCAPT_MULTI_PROFILE
/* Run after native RF/NV initialization, before RX events or capture DMA.
 * Native rf_get_freq leaves the previous NV row untouched on no match.
 * Read the mutable post-NV channel table, never assume table row==NV row.
 * Return one plus the NV row, or zero for missing/unknown configuration.
 * This proves a calibration entry exists, not physical reception support. */
static __attribute__((noinline)) uint32_t terminal_profile_nv_row(uint32_t channel)
{
    volatile const uint16_t *bands=(volatile const uint16_t *)0x8047190eu;
    volatile const uint16_t *minimum=(volatile const uint16_t *)0x80471944u;
    volatile const uint16_t *maximum=(volatile const uint16_t *)0x8047197au;
    volatile const uint16_t *nv=(volatile const uint16_t *)0x804f42d8u;
    for(unsigned row=0;row<27u;++row) {
        if(channel<minimum[row] || channel>maximum[row]) continue;
        uint32_t wanted=bands[row];
        if(wanted==18u || wanted==19u || wanted==26u) wanted=5u;
        else if(wanted==25u) wanted=2u;
        else if(wanted==45u) wanted=61u;
        else if(wanted==59u) wanted=62u;
        for(unsigned i=0;i<24u;++i) if(nv[i]==wanted && wanted) return i+1u;
        return 0;
    }
    return 0;
}
#endif
#endif
