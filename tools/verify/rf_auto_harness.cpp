#include <cassert>
#include <cstdint>
#include "../../host/common/RfAuto.hpp"
#include "routes.hpp"
int main() {
    auto all=[](uint32_t){return true;};
    auto choose=[&](uint32_t hz,uint32_t current=0){return uis8910::autoRoute(routes,hz,current,all);};
    assert(choose(499999900)==0);
    assert(choose(500000000)==5);
    assert(choose(699999900)==5);
    assert(choose(700000000)==5);
    assert(choose(800000000)==5);
    assert(choose(824000000)==5);
    assert(choose(880000000,8)==5);
    assert(choose(915000000,8)==5);
    assert(choose(917500000,5)==5);
    assert(choose(917500000,8)==8);
    assert(choose(920000000,5)==8);
    assert(choose(925000000)==8);
    assert(choose(925000100)==8);
    assert(choose(1000000000)==8);
    assert(choose(1000000100)==0);
    assert(choose(1350000000)==0);
    assert(choose(1374999900)==0);
    for(uint32_t hz:{1375000000u,1400000000u,1447000000u,1500000000u,1600000000u,1650000000u,1680000000u})
        assert(choose(hz)==3);
    assert(uis8910::autoRoute(routes,1375000000u,3,[](uint32_t b){return b!=3;})==0);
    assert(choose(1710000000)==3);
    assert(choose(1842500000)==3);
    assert(choose(1900000000,3)==3);
    assert(choose(1900000000,40)==40);
    assert(choose(1885000000,40)==3);
    assert(choose(1890000000,40)==3);
    assert(choose(1890000100,40)==40);
    assert(choose(2000000000)==40);
    assert(choose(2600000000,7)==40);
    assert(choose(2786000000u)==40);
    assert(choose(2790625000u)==0);
    assert(choose(881500001)==0);
    assert(choose(0)==0);
    assert(uis8910::autoRoute(routes,2600000000u,40,[](uint32_t b){return b!=40;})==0);
    assert(uis8910::autoRoute(routes,1900000000u,40,[](uint32_t b){return b!=40;})==3);
    // Walk the full request space at100kHz. Never choose a manual-only path,
    // cross a profile bound or select an unavailable calibration candidate.
    for(uint32_t hz=0;hz<3000000000u;hz+=100000) {
        uint32_t band=choose(hz,40);
        if(!band)continue;
        assert(uis8910::autoCandidate(band));bool found=false;
        for(const auto &r:routes)if(r.band==band && hz>=r.low && hz<=r.high)found=true;
        assert(found);
    }
}
