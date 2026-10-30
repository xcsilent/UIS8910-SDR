#ifndef UIS8910_RF_AUTO_H
#define UIS8910_RF_AUTO_H
#include <stdint.h>
/* Provisional routing policy; an eligible software envelope is not RF proof. */
static inline uint32_t uis_auto_bit(uint32_t band) {
    switch(band) {case 5:return 1;case 8:return 2;case 3:return 4;case 40:return 8;default:return 0;}
}
static inline uint32_t uis_auto_choose(uint32_t mask,uint32_t hz,uint32_t current) {
    static const uint32_t priority[]={5,8,3,40};
    if(hz%100) return 0;
    /* Caller supplies eligible paths from the shared profile table and
     * runtime availability. Manual unrestricted bounds are not eligibility.
     * Keep policy/hysteresis here, frequency envelopes in one table. */
    /* Provisional hysteresis from B5/B8 overlap reference measurements. */
    if((mask&3u)==3u) {
        if(current==5u && hz<920000000u)return 5u;
        if(current==8u && hz>915000000u)return 8u;
        return hz>=920000000u?8u:5u;
    }
    /* Provisional board-specific guard: B40 failed the 1885 MHz reference
       while B3 worked at 1884.375 MHz. Keep margin; not a physical limit. */
    if((mask&12u)==12u && hz<=1890000000u)return 3u;
    if(mask&uis_auto_bit(current))return current;
    for(unsigned i=0;i<4;++i)if(mask&uis_auto_bit(priority[i]))return priority[i];
    return 0;
}
#endif
