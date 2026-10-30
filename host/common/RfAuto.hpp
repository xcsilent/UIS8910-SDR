#pragma once
#include <cstdint>
#include <initializer_list>
#include "rf_auto.h"

// Provisional coverage policy, not a calibrated sensitivity or physical range
// claim. Bounds come from the same generated C-profile table as manual routes.
// Extra routes are opt-in diagnostics until they add coverage/quality evidence.
namespace uis8910 {
inline uint32_t autoQualityMax(uint32_t band) {
    // B40 remains manually tunable above this point, but 2786 MHz is the
    // highest center with complete reference evidence under the current
    // antenna/reference setup; higher points show degraded tracking.
    return band==40u ? 2786000000u : 4294967200u;
}
inline bool autoCandidate(uint32_t band) {
    return uis_auto_bit(band)!=0;
}
template<class Routes, class Available>
uint32_t autoRoute(const Routes &routes,uint32_t hz,uint32_t current,Available available) {
    if(hz%100)return 0;
    auto usable=[&](uint32_t band) {
        if(!autoCandidate(band) || !available(band))return false;
        for(const auto &r:routes)if(r.band==band)return hz>=r.low && hz<=r.high && hz<=autoQualityMax(band);
        return false;
    };
    uint32_t mask=0;
    for(uint32_t band:{5u,8u,3u,40u})if(usable(band))mask|=uis_auto_bit(band);
    return uis_auto_choose(mask,hz,current);
}
}
